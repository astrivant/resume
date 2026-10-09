"""
Persist capture plans and validate deterministic LinkedIn section shards.
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, Literal

import cattrs
from attrs import evolve, frozen

from resumeme.compiler.asts.profile import Profile, Section

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

__all__ = [
    "CapturePlan",
    "CaptureRoute",
    "CaptureShard",
    "aggregate_capture",
    "assign_routes",
    "load_capture_plan",
    "load_capture_shard",
    "make_capture_plan",
    "save_capture_plan",
    "save_capture_shard",
]

BrowserName = Literal["firefox", "chrome"]
RouteKind = Literal["detail", "inline", "contact"]
_SHARD_COUNT = 6
_converter = cattrs.Converter(forbid_extra_keys=True)


@frozen
class CaptureRoute:
    """
    Describe one independently collectible profile section.

    Attributes:
        key (str): Canonical profile section key, unique within the plan.
        title (str): LinkedIn heading used for navigation and diagnostics.
        url (str): Owner-scoped LinkedIn route to collect.
        kind (RouteKind): Detail page, inline tabs, or contact overlay.
        weight (int): Estimated section size used to balance six workers.
    """

    key: str
    title: str
    url: str
    kind: RouteKind
    weight: int = 1


@frozen
class CapturePlan:
    """
    Bind a base profile snapshot to its complete list of section routes.

    Attributes:
        capture_id (str): Unique identity shared by all outputs from this capture.
        browser (BrowserName): Browser engine whose session bootstrapped the plan.
        shard_count (int): Required number of capture workers.
        profile (Profile): Profile overview and preview sections collected once.
        routes (list[CaptureRoute]): Detail sections to distribute across workers.
    """

    capture_id: str
    browser: BrowserName
    shard_count: int
    profile: Profile
    routes: list[CaptureRoute]


@frozen
class CaptureShard:
    """
    Record one worker's complete output and assigned browser identity.

    Attributes:
        capture_id (str): Plan identity this shard belongs to.
        browser (BrowserName): Browser engine used by this worker.
        shard_index (int): One-based worker index.
        shard_count (int): Total workers expected by the plan.
        sections (list[Section]): Fully collected sections owned by this worker.
    """

    capture_id: str
    browser: BrowserName
    shard_index: int
    shard_count: int
    sections: list[Section]


def make_capture_plan(profile: Profile, browser: BrowserName, routes: Iterable[CaptureRoute]) -> CapturePlan:
    """
    Create a six-worker plan after validating owner-scoped, unique routes.

    Args:
        profile (Profile): Authenticated profile overview.
        browser (BrowserName): Selected browser engine.
        routes (Iterable[CaptureRoute]): Detail routes discovered on the profile page.

    Returns:
        CapturePlan: Plan shared by the bootstrap job and all six workers.

    Raises:
        ValueError: A route is duplicated, unsafe, or incompatible with the profile owner.
    """
    plan = CapturePlan(
        capture_id=uuid.uuid4().hex,
        browser=browser,
        shard_count=_SHARD_COUNT,
        profile=profile,
        routes=list(routes),
    )
    _validate_plan(plan)
    return plan


def assign_routes(plan: CapturePlan) -> dict[int, list[CaptureRoute]]:
    """
    Balance larger profile sections across workers deterministically.

    Args:
        plan (CapturePlan): Validated six-worker capture plan.

    Returns:
        dict[int, list[CaptureRoute]]: One-based shard numbers mapped to ordered routes.
    """
    buckets: dict[int, list[CaptureRoute]] = {index: [] for index in range(1, plan.shard_count + 1)}
    loads = {index: 0 for index in buckets}
    order = {route.key: index for index, route in enumerate(plan.routes)}

    # Greedy size balancing gives long sections separate workers while key-based ties keep assignments repeatable.
    for route in sorted(plan.routes, key=lambda item: (-item.weight, item.key)):
        shard = min(loads, key=lambda index: (loads[index], index))
        buckets[shard].append(route)
        loads[shard] += route.weight

    for routes in buckets.values():
        routes.sort(key=lambda item: order[item.key])

    return buckets


def aggregate_capture(plan: CapturePlan, shards: Iterable[CaptureShard]) -> Profile:
    """
    Replace overview previews only after every planned route has one validated result.

    Args:
        plan (CapturePlan): Validated profile overview and route assignment.
        shards (Iterable[CaptureShard]): Outputs downloaded from all parallel workers.

    Returns:
        Profile: Complete profile with detail sections restored to LinkedIn's source order.

    Raises:
        ValueError: A shard is missing, duplicated, misrouted, or contains an incomplete route set.
    """
    expected = assign_routes(plan)
    by_index: dict[int, CaptureShard] = {}

    for shard in shards:
        _validate_shard(shard, plan)

        if shard.shard_index in by_index:
            raise ValueError(f"Capture shard {shard.shard_index} was supplied more than once.")

        by_index[shard.shard_index] = shard

    required_indices = set(expected)

    if by_index.keys() != required_indices:
        missing = sorted(required_indices - by_index.keys())
        extra = sorted(by_index.keys() - required_indices)
        raise ValueError(f"Capture shards do not cover the plan (missing={missing}, unexpected={extra}).")

    collected: dict[str, Section] = {}

    for index, shard in by_index.items():
        expected_keys = {route.key for route in expected[index]}
        actual_keys = {section.key for section in shard.sections}

        if actual_keys != expected_keys:
            raise ValueError(
                f"Capture shard {index} returned an incomplete route set "
                f"(missing={sorted(expected_keys - actual_keys)}, unexpected={sorted(actual_keys - expected_keys)})."
            )

        collected.update((section.key, section) for section in shard.sections)

    # Keep overview-only sections intact and replace a preview only with the complete result assigned to its route.
    sections = [collected.pop(section.key, section) for section in plan.profile.sections]
    sections.extend(collected.values())
    return evolve(plan.profile, sections=sections)


def save_capture_plan(plan: CapturePlan, path: Path) -> None:
    """
    Atomically write a plan that contains no browser state or authentication material.

    Args:
        plan (CapturePlan): Validated plan to serialize.
        path (Path): Destination path relative to the project.

    Returns:
        None: The complete plan replaces the destination file.
    """
    _validate_plan(plan)
    _write_json(path, plan)


def load_capture_plan(path: Path) -> CapturePlan:
    """
    Read a plan and reject malformed or cross-owner routes before opening a browser.

    Args:
        path (Path): Serialized plan path.

    Returns:
        CapturePlan: Validated capture plan.

    Raises:
        ValueError: The file is invalid or its routes do not belong to the captured owner.
    """
    plan = _converter.structure(json.loads(path.read_text(encoding="utf-8")), CapturePlan)
    _validate_plan(plan)
    return plan


def save_capture_shard(shard: CaptureShard, path: Path) -> None:
    """
    Atomically write a single worker's collected sections.

    Args:
        shard (CaptureShard): Completed worker result.
        path (Path): Destination path relative to the project.

    Returns:
        None: The complete shard replaces the destination file.
    """
    _validate_shard_shape(shard)
    _write_json(path, shard)


def load_capture_shard(path: Path) -> CaptureShard:
    """
    Read a worker artifact into typed profile sections.

    Args:
        path (Path): Serialized shard path.

    Returns:
        CaptureShard: Structurally validated worker result.

    Raises:
        ValueError: The file is invalid or repeats a section key.
    """
    shard = _converter.structure(json.loads(path.read_text(encoding="utf-8")), CaptureShard)
    _validate_shard_shape(shard)
    return shard


def _validate_plan(plan: CapturePlan) -> None:
    """
    Enforce the browser, shard, ownership, and route contracts used by the worker matrix.

    Args:
        plan (CapturePlan): Plan under validation.

    Returns:
        None: The plan is safe to distribute to workers.

    Raises:
        ValueError: A plan field or route violates the capture contract.
    """
    if not plan.capture_id or plan.browser not in {"firefox", "chrome"} or plan.shard_count != _SHARD_COUNT:
        raise ValueError("Capture plan must identify a supported browser and exactly six shards.")

    if not plan.profile.username or not plan.profile.name:
        raise ValueError("Capture plan must contain an identified profile overview.")

    route_keys: set[str] = set()
    prefix = f"https://www.linkedin.com/in/{plan.profile.username.casefold()}/"

    for route in plan.routes:
        if (
            not route.key
            or route.key in route_keys
            or not route.title
            or route.kind not in {"detail", "inline", "contact"}
            or route.weight < 1
            or not route.url.casefold().startswith(prefix)
        ):
            raise ValueError(f"Capture route {route.key!r} is duplicated, invalid, or outside the configured LinkedIn profile.")

        route_keys.add(route.key)


def _validate_shard(shard: CaptureShard, plan: CapturePlan) -> None:
    """
    Bind a worker result to the exact plan, browser, and assigned shard number.

    Args:
        shard (CaptureShard): Worker output.
        plan (CapturePlan): Authoritative plan.

    Returns:
        None: The output is eligible for aggregation.

    Raises:
        ValueError: The worker output belongs to a different plan or browser.
    """
    _validate_shard_shape(shard)

    if (
        shard.capture_id != plan.capture_id
        or shard.browser != plan.browser
        or shard.shard_count != plan.shard_count
        or not 1 <= shard.shard_index <= plan.shard_count
    ):
        raise ValueError(f"Capture shard {shard.shard_index} does not match this plan's browser or identity.")


def _validate_shard_shape(shard: CaptureShard) -> None:
    """
    Reject structurally invalid worker metadata and repeated section output.

    Args:
        shard (CaptureShard): Worker output under validation.

    Returns:
        None: The worker output has a unique section set and supported metadata.

    Raises:
        ValueError: The metadata is invalid or a section key appears more than once.
    """
    keys = [section.key for section in shard.sections]

    if (
        not shard.capture_id
        or shard.browser not in {"firefox", "chrome"}
        or shard.shard_count != _SHARD_COUNT
        or not 1 <= shard.shard_index <= shard.shard_count
        or not all(keys)
        or len(keys) != len(set(keys))
    ):
        raise ValueError("Capture shard metadata or section keys are invalid.")


def _write_json(path: Path, value: object) -> None:
    """
    Publish structured capture data atomically within its destination directory.

    Args:
        path (Path): Target JSON path.
        value (object): Typed object converted to JSON-compatible data.

    Returns:
        None: The target contains the complete serialized value.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + ".pending")
    pending.write_text(json.dumps(_converter.unstructure(value), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pending.replace(path)
