"""
Verify nested employment presentation, role ownership, and legacy progression boundaries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from attrs import evolve
from PIL import Image

from resumeme.compiler.asts.profile import Entry, Link, Media, Profile, Section
from resumeme.compiler.passes.progression import experience_layout
from resumeme.compiler.pipeline import render_profile
from resumeme.config import Config, Experience, JobSelector, LinkedIn

if TYPE_CHECKING:
    from pathlib import Path


def test_structured_roles_keep_company_context_and_own_their_content() -> None:
    """
    Separate company metadata from complete roles without duplicating shared branding.

    Returns:
        None: Role content remains nested, the employer logo appears on the parent, and the input stays unchanged.
    """
    logo = Media("https://example.org/logo.png", alt="Example logo", path="logo.png", link="https://example.org/company")
    link = Link("Example", logo.link)
    figure = Media("https://example.org/figure.png", path="figure.png")
    current = Entry("Staff", ["2022 - Present", "Current work"], links=[link], images=[logo, figure])
    previous = Entry("Engineer", ["2020 - 2022", "Earlier work"], links=[link], images=[logo])
    group = Entry(
        "Example",
        ["Full-time \u00b7 6 yrs", current.title, *current.paragraphs, previous.title, *previous.paragraphs],
        links=[link],
        images=[logo, figure],
        positions=[current, previous],
    )
    display = experience_layout(group)
    assert display.paragraphs == ["Full-time \u00b7 6 yrs"]
    assert display.images == [logo]
    assert display.positions[0].images == [figure]
    assert display.positions[1].images == []
    assert all(not role.links for role in display.positions)
    assert [role.paragraphs for role in display.positions] == [current.paragraphs, previous.paragraphs]
    assert group.positions == [current, previous]
    assert group.images == [logo, figure]


def test_legacy_groups_split_only_role_text_at_title_date_boundaries() -> None:
    """
    Render older flattened snapshots as progressions without assigning guessed media ownership.

    Returns:
        None: Text order is preserved exactly and legacy references stay at company scope.
    """
    lines = [
        "Full-time \u00b7 4 yrs",
        "Boston",
        "Senior Engineer",
        "2022 - 2024",
        "Led delivery",
        "Engineer",
        "2020 - 2022",
        "Built systems",
    ]
    link = Link("Reference", "https://example.org/reference")
    group = Entry("Example", lines, links=[link])
    display = experience_layout(group)
    assert display.paragraphs == lines[:2]
    assert [role.title for role in display.positions] == ["Senior Engineer", "Engineer"]
    assert display.links == [link]
    assert all(not role.links for role in display.positions)
    assert [*display.paragraphs, *(line for role in display.positions for line in [role.title, *role.paragraphs])] == lines
    assert group.positions == []


@pytest.mark.parametrize(
    "lines",
    [
        ["Example", "2020 - Present", "Ordinary role"],
        ["2022 - 2024", "Engineer", "2020 - 2022"],
        ["Responsibilities", "2022 - 2024", "Engineer", "2020 - 2022"],
        ["- A dated delivery milestone", "2022 - 2024", "Engineer", "2020 - 2022"],
    ],
)
def test_ambiguous_legacy_dates_do_not_create_nested_roles(lines: list[str]) -> None:
    """
    Retain standalone jobs and ambiguous date sequences as ordinary content.

    Args:
        lines (list[str]): Employment text lacking two usable role boundaries.

    Returns:
        None: Layout does not invent a career progression from prose or incomplete metadata.
    """
    entry = Entry("Example", lines)
    assert experience_layout(entry) == entry


@pytest.mark.parametrize("filtered", [False, True])
def test_role_progression_renders_once_after_job_filters(tmp_path: Path, filtered: bool) -> None:
    """
    Render retained roles under one employer with a shared vertical rule and preserved locations.

    Args:
        tmp_path (Path): Isolated rendering directory.
        filtered (bool): Whether an older role is explicitly excluded.

    Returns:
        None: Employer branding and each retained role appear once; excluded roles contribute no visible content.
    """
    Image.new("RGB", (20, 20), "blue").save(tmp_path / "logo.png")
    logo = Media("https://example.org/logo.png", alt="Example logo", path="logo.png", link="https://www.linkedin.com/company/example/")
    current = Entry("Staff Engineer", ["2022 - Present", "Boston, MA", "Current delivery"])
    previous = Entry("Engineer", ["2020 - 2022", "Earlier delivery"])
    group = Entry(
        "Example",
        ["Full-time \u00b7 6 yrs", current.title, *current.paragraphs, previous.title, *previous.paragraphs],
        images=[logo],
        positions=[current, previous],
    )
    config = Config(LinkedIn("example-person"))

    if filtered:
        config = evolve(config, experience=Experience(disable=[JobSelector(title="Engineer", company="Example")]))

    profile = Profile("example-person", "Alex", sections=[Section("experience", "Experience", [group])])
    text = render_profile(profile, config, tmp_path).read_text().split(r"\begin{document}", 1)[1]
    assert text.count(r"\begin{roleprogression}") == 1

    # Filtering down to one role restores the normal connector rather than suggesting a remaining progression.
    assert (r"\begin{roleprogression}[70]" in text) is not filtered

    company_heading = r"\hypertarget{resumeme-section-0-job-0}{}"
    assert text.index(company_heading) < text.index(r"\companytext{Example}")
    current_heading = r"\roletitle{\hypertarget{resumeme-section-0-job-0-0}{}Staff Engineer}"
    previous_heading = r"\roletitle{\hypertarget{resumeme-section-0-job-0-1}{}Engineer}"
    assert text.count(current_heading) == 1
    assert text.count("Current delivery") == 1
    assert text.count(r"\includegraphics[") == 1
    assert "https://www.google.com/maps/search/" in text
    assert (previous_heading in text) is not filtered
    assert ("Earlier delivery" in text) is not filtered
    assert text.index(company_heading) < text.index(r"\begin{roleprogression}") < text.index(current_heading)


@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("mode", ["Remote", "On-site", "Hybrid"])
def test_nested_role_work_mode_follows_duration(structured: bool, mode: str) -> None:
    """
    Compact work arrangements in both legacy and structured company progressions.

    Args:
        structured (bool): Whether capture recorded explicit role boundaries.
        mode (str): Supported standalone work arrangement.

    Returns:
        None: Each mode follows its duration once and captured paragraphs remain intact.
    """
    current = Entry("Engineer", ["Apr 2021 - Jul 2021 \u00b7 4 mos", mode, "Built systems"])
    previous = Entry("Associate", ["Jan 2021 - Mar 2021 \u00b7 3 mos", "On-site", "Earlier work"])
    lines = ["Full-time \u00b7 7 mos", current.title, *current.paragraphs, previous.title, *previous.paragraphs]
    group = Entry("Example", lines, positions=[current, previous] if structured else [])
    display = experience_layout(group)
    assert display.positions[0].paragraphs == [f"Apr 2021 - Jul 2021 \u00b7 4 mos \u00b7 {mode}", "Built systems"]
    assert display.positions[1].paragraphs == ["Jan 2021 - Mar 2021 \u00b7 3 mos \u00b7 On-site", "Earlier work"]
    assert current.paragraphs == ["Apr 2021 - Jul 2021 \u00b7 4 mos", mode, "Built systems"]
    assert group.paragraphs == lines
    assert experience_layout(current) == current


def test_nested_work_mode_retains_clickable_geography(tmp_path: Path) -> None:
    """
    Keep location links and role anchors after moving the arrangement into date metadata.

    Args:
        tmp_path (Path): Isolated template rendering directory.

    Returns:
        None: Only metadata placement changes; the visible location remains a Google Maps link.
    """
    current = Entry("Engineer", ["Apr 2021 - Jul 2021 \u00b7 4 mos", "Boston, MA \u00b7 Remote", "Built systems"])
    previous = Entry("Associate", ["Jan 2021 - Mar 2021 \u00b7 3 mos", "On-site", "Earlier work"])
    group = Entry("Example", [current.title, *current.paragraphs, previous.title, *previous.paragraphs], positions=[current, previous])
    profile = Profile("example-person", "Alex", sections=[Section("experience", "Experience", [group])])
    source = render_profile(profile, Config(LinkedIn(profile.username)), tmp_path).read_text()
    assert "\\profileparagraph{Apr 2021 - Jul 2021 \u00b7 4 mos \u00b7 Remote}" in source
    assert "\\profileparagraph{Jan 2021 - Mar 2021 \u00b7 3 mos \u00b7 On-site}" in source
    assert r"\href{https://www.google.com/maps/search/?api=1\&query=Boston\%2C+MA}{Boston, MA}" in source
    assert r"\hypertarget{resumeme-section-0-job-0-0}" in source
    assert r"\profileparagraph{On-site}" not in source
    assert current.paragraphs[1] == "Boston, MA \u00b7 Remote"


@pytest.mark.parametrize(
    "paragraphs",
    [
        ["2021 - 2022 \u00b7 1 yr", "Remote systems delivery"],
        ["2021 - 2022 \u00b7 1 yr", "Responsibilities", "Remote"],
        ["2021 - 2022 \u00b7 1 yr", "- Built systems \u00b7 Remote"],
        ["2021 - 2022 \u00b7 1 yr \u00b7 Hybrid", "On-site"],
        ["Remote", "Undated role"],
    ],
)
def test_work_mode_compaction_leaves_ambiguous_body_text_unchanged(paragraphs: list[str]) -> None:
    """
    Avoid moving prose, undated arrangements, or conflicting metadata into the header.

    Args:
        paragraphs (list[str]): Role text without an unambiguous adjacent work-mode row.

    Returns:
        None: The role's display text is preserved verbatim.
    """
    role = Entry("Engineer", paragraphs)
    group = Entry("Example", [role.title, *paragraphs], positions=[role])
    assert experience_layout(group).positions[0].paragraphs == paragraphs


def test_existing_date_work_mode_is_not_duplicated() -> None:
    """
    Remove a repeated standalone arrangement without adding another date suffix.

    Returns:
        None: The displayed role retains exactly one occurrence of its work mode.
    """
    role = Entry("Engineer", ["2021 - 2022 \u00b7 1 yr \u00b7 Remote", "Remote", "Built systems"])
    group = Entry("Example", [role.title, *role.paragraphs], positions=[role])
    display = experience_layout(group).positions[0]
    assert display.paragraphs == ["2021 - 2022 \u00b7 1 yr \u00b7 Remote", "Built systems"]
    assert experience_layout(display) == display
