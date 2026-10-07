"""
Prepare company context and nested roles for employment progression rendering.
"""

from __future__ import annotations

from attrs import evolve

from resumeme.compiler.asts.dates import employment_period
from resumeme.compiler.asts.profile import Entry
from resumeme.compiler.constants.locations import WORK_MODES
from resumeme.compiler.passes.experience import regroup_positions
from resumeme.compiler.passes.lists import text_blocks
from resumeme.compiler.passes.locations import job_locations
from resumeme.compiler.passes.media import employer_badge

__all__ = ["experience_layout"]


def _role_metadata(entry: Entry) -> Entry:
    """
    Move a nested role's work arrangement onto its dates and duration row.

    Args:
        entry (Entry): Individual role separated from its company context.

    Returns:
        Entry: Display copy with compact metadata, retaining geography and description text.
    """

    # Only inspect the header's first date row and its immediate successor; work-mode words in prose stay untouched.
    dated = next((index for index, line in enumerate(entry.paragraphs[:3]) if employment_period(line)), None)

    if dated is None or dated + 1 >= len(entry.paragraphs):
        return entry

    metadata = entry.paragraphs[dated + 1].strip()
    place, separator, mode = metadata.rpartition("\u00b7")
    mode = mode.strip()

    if mode.casefold() not in WORK_MODES or (separator and metadata not in job_locations(entry)):
        return entry

    # Preserve any clickable place on its own row; never duplicate a mode already present in the date metadata.
    dates = entry.paragraphs[dated].rstrip()
    existing_modes = {part.strip().casefold() for part in dates.split("\u00b7")[1:]} & WORK_MODES

    if existing_modes and mode.casefold() not in existing_modes:
        return entry

    combined = dates if existing_modes else f"{dates} \u00b7 {mode}"
    replacement = [combined, place.rstrip()] if separator else [combined]
    return evolve(entry, paragraphs=[*entry.paragraphs[:dated], *replacement, *entry.paragraphs[dated + 2 :]])


def experience_layout(entry: Entry) -> Entry:
    """
    Separate company metadata from role text after exclusions and project consolidation.

    Args:
        entry (Entry): Staged employment record with structured or legacy flattened positions.

    Returns:
        Entry: Display copy containing company-only paragraphs and ordered child roles, or the unchanged standalone entry.

    Raises:
        ValueError: Structured positions cannot be reconciled with the flattened company text.
    """
    if entry.positions:
        # Reuse recorded boundaries; shared employer branding belongs on the company row, not on every role.
        company = regroup_positions(entry, [None] * len(entry.positions))
        badge = employer_badge(entry)
        logo = badge[1] if badge and badge[0] == -1 else None
        images = [*company.images]

        if logo and logo not in images:
            images.insert(0, logo)

        positions = [
            evolve(
                _role_metadata(position),
                images=[image for image in position.images if not logo or image.url != logo.url],
                links=[link for link in position.links if not logo or not logo.link or (link.resolved_url or link.url) != logo.link],
            )
            for position in entry.positions
        ]
        return evolve(company, images=images, positions=positions)

    # Legacy snapshots have no media ownership per role; split only text and retain all references on the company.
    dates = [index for index, line in enumerate(entry.paragraphs) if employment_period(line)]

    if len(dates) < 2 or dates[0] == 0:
        return entry

    starts = [index - 1 for index in dates]

    for start in starts:
        title = entry.paragraphs[start]
        blocks = text_blocks([title])

        # A dated bullet or another metadata row does not establish a role boundary.
        if (
            not title.strip()
            or employment_period(title)
            or len(blocks) != 1
            or blocks[0].depth is not None
            or title.strip().casefold().rstrip(":") in {"responsibilities", "projects", "technologies", "skills"}
        ):
            return entry

    ends = [*starts[1:], len(entry.paragraphs)]
    positions = [
        _role_metadata(Entry(entry.paragraphs[start], entry.paragraphs[start + 1 : end])) for start, end in zip(starts, ends, strict=True)
    ]
    return evolve(entry, paragraphs=entry.paragraphs[: starts[0]], positions=positions)
