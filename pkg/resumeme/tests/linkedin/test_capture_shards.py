"""
Verify route partitioning, artifact validation, and complete profile aggregation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from attrs import evolve

from resumeme.cli import main
from resumeme.compiler.asts.profile import Entry, Profile, Section, load_profile
from resumeme.linkedin.capture.shards import (
    CaptureRoute,
    CaptureShard,
    aggregate_capture,
    assign_routes,
    load_capture_plan,
    load_capture_shard,
    make_capture_plan,
    save_capture_plan,
    save_capture_shard,
)

if TYPE_CHECKING:
    from pathlib import Path


def _profile() -> Profile:
    """
    Build a base snapshot with one preview and one overview-only section.

    Returns:
        Profile: Minimal source for route and aggregation tests.
    """
    return Profile(
        username="example-person",
        name="Alex Example",
        sections=[
            Section("experience", "Experience", [Entry("Preview role")]),
            Section("about", "About", [Entry("Overview text")]),
        ],
    )


def _routes(count: int = 11) -> list[CaptureRoute]:
    """
    Create owner-scoped routes with uneven estimated collection costs.

    Args:
        count (int): Number of routes to generate.

    Returns:
        list[CaptureRoute]: Deterministic route list for partitioning tests.
    """
    return [
        CaptureRoute(
            key=f"section-{index}",
            title=f"Section {index}",
            url=f"https://www.linkedin.com/in/example-person/details/section-{index}/",
            kind="detail",
            weight=index + 1,
        )
        for index in range(count)
    ]


def test_route_assignment_is_complete_deterministic_and_balanced() -> None:
    """
    Assign every section once while distributing larger sections across six workers.

    Returns:
        None: Repeated planning yields the same complete assignments with balanced estimated load.
    """
    plan = make_capture_plan(_profile(), "firefox", _routes())
    assignments = assign_routes(plan)

    assert list(assignments) == [1, 2, 3, 4, 5, 6]
    assert assignments == assign_routes(plan)
    assert sorted(route.key for routes in assignments.values() for route in routes) == sorted(route.key for route in plan.routes)
    loads = [sum(route.weight for route in routes) for routes in assignments.values()]
    assert max(loads) - min(loads) <= max(route.weight for route in plan.routes)


def test_plan_rejects_duplicate_and_cross_owner_routes() -> None:
    """
    Keep route manifests bound to the configured profile and canonical section keys.

    Returns:
        None: Duplicate keys and external profile routes fail before a browser can navigate them.
    """
    route = _routes(1)[0]

    with pytest.raises(ValueError, match="duplicated"):
        make_capture_plan(_profile(), "firefox", [route, route])

    with pytest.raises(ValueError, match="outside the configured"):
        make_capture_plan(_profile(), "firefox", [evolve(route, url="https://www.linkedin.com/in/another-person/details/x/")])


def test_plan_and_shards_round_trip_as_typed_artifacts(tmp_path: Path) -> None:
    """
    Preserve typed profile records and metadata across separate Actions artifact transfers.

    Args:
        tmp_path (Path): Isolated artifact staging directory.

    Returns:
        None: The restored plan and shard remain eligible for strict aggregation.
    """
    plan_path = tmp_path / "plan.json"
    shard_path = tmp_path / "shard.json"
    plan = make_capture_plan(_profile(), "chrome", _routes(1))
    save_capture_plan(plan, plan_path)
    restored = load_capture_plan(plan_path)
    section = Section("section-0", "Section 0", [Entry("Collected detail")])
    shard = CaptureShard(plan.capture_id, "chrome", 1, 6, [section])
    save_capture_shard(shard, shard_path)

    assert restored == plan
    assert load_capture_shard(shard_path) == shard
    shards = [shard, *(CaptureShard(plan.capture_id, "chrome", index, 6, []) for index in range(2, 7))]
    assert aggregate_capture(restored, shards).sections[-1].entries[0].title == "Collected detail"


def test_aggregation_requires_all_six_shards_and_every_assigned_route() -> None:
    """
    Refuse to publish partial output when a worker or section is missing.

    Returns:
        None: Missing workers and route results fail with actionable diagnostics.
    """
    plan = make_capture_plan(_profile(), "firefox", _routes())
    assignments = assign_routes(plan)
    shards = [
        CaptureShard(
            plan.capture_id,
            "firefox",
            index,
            6,
            [Section(route.key, route.title, [Entry(f"Collected {route.key}")]) for route in routes],
        )
        for index, routes in assignments.items()
    ]

    with pytest.raises(ValueError, match=r"missing=\[6\]"):
        aggregate_capture(plan, shards[:-1])

    incomplete = [*shards]
    incomplete[0] = evolve(incomplete[0], sections=[])

    with pytest.raises(ValueError, match="incomplete route set"):
        aggregate_capture(plan, incomplete)


def test_aggregation_restores_profile_order_and_preserves_preview_only_sections() -> None:
    """
    Replace detailed previews without dropping overview-only content.

    Returns:
        None: The final profile retains source order and replaces only assigned sections.
    """
    plan = make_capture_plan(_profile(), "firefox", _routes(1))
    assignments = assign_routes(plan)
    shards = [
        CaptureShard(
            plan.capture_id,
            "firefox",
            index,
            6,
            [Section(route.key, route.title, [Entry("Complete detail")]) for route in routes],
        )
        for index, routes in assignments.items()
    ]

    profile = aggregate_capture(plan, shards)

    assert [section.key for section in profile.sections] == ["experience", "about", "section-0"]
    assert profile.sections[0].entries[0].title == "Preview role"
    assert profile.sections[1].entries[0].title == "Overview text"
    assert profile.sections[2].entries[0].title == "Complete detail"


def test_aggregation_rejects_another_browser_or_capture_id() -> None:
    """
    Keep browser session and profile-plan provenance consistent across all shards.

    Returns:
        None: A worker from another browser or workflow capture cannot contribute output.
    """
    plan = make_capture_plan(_profile(), "firefox", [])

    with pytest.raises(ValueError, match="does not match"):
        aggregate_capture(plan, [CaptureShard(plan.capture_id, "chrome", index, 6, []) for index in range(1, 7)])

    with pytest.raises(ValueError, match="does not match"):
        aggregate_capture(plan, [CaptureShard("another-capture", "firefox", index, 6, []) for index in range(1, 7)])


def test_aggregate_cli_writes_only_a_complete_validated_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Exercise the user-facing aggregation command with six transferred shard artifacts.

    Args:
        tmp_path (Path): Isolated CLI checkout and shard artifact directory.
        monkeypatch (pytest.MonkeyPatch): Replaces remote media requests with identity behavior.

    Returns:
        None: The complete result validates as an ordinary profile snapshot and a missing shard cannot overwrite it.
    """
    (tmp_path / "resumeme.config.yaml").write_text("linkedin: {username: example-person}\n", encoding="utf-8")
    plan = make_capture_plan(_profile(), "firefox", _routes(1))
    plan_path = tmp_path / ".cache/capture/plan.json"
    shard_directory = tmp_path / ".cache/capture/shards"
    shard_directory.mkdir(parents=True)
    save_capture_plan(plan, plan_path)

    for index in range(1, 7):
        sections = [Section(route.key, route.title, [Entry(f"Collected {route.key}")]) for route in assign_routes(plan)[index]]
        save_capture_shard(
            CaptureShard(plan.capture_id, "firefox", index, 6, sections, {section.key: 12.0 for section in sections}),
            shard_directory / f"shard-{index}.json",
        )

    monkeypatch.setattr("resumeme.cli.cache_media", lambda profile, config, root: profile)
    arguments = ["--config", str(tmp_path / "resumeme.config.yaml"), "aggregate"]

    assert main(arguments) == 0
    snapshot = tmp_path / "data/profile.json"
    first = snapshot.read_bytes()
    timings = tmp_path / ".cache/capture/timings.json"
    previous_feedback = timings.read_bytes()
    assert load_profile(snapshot, "example-person").sections[-1].entries[0].title == "Collected section-0"

    (shard_directory / "shard-6.json").unlink()

    assert main(arguments) == 2
    assert snapshot.read_bytes() == first
    assert timings.read_bytes() == previous_feedback
