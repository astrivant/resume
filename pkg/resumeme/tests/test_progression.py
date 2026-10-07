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
        ["Full-time · 6 yrs", current.title, *current.paragraphs, previous.title, *previous.paragraphs],
        links=[link],
        images=[logo, figure],
        positions=[current, previous],
    )
    display = experience_layout(group)
    assert display.paragraphs == ["Full-time · 6 yrs"]
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
    lines = ["Full-time · 4 yrs", "Boston", "Senior Engineer", "2022 - 2024", "Led delivery", "Engineer", "2020 - 2022", "Built systems"]
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
        ["Full-time · 6 yrs", current.title, *current.paragraphs, previous.title, *previous.paragraphs],
        images=[logo],
        positions=[current, previous],
    )
    config = Config(LinkedIn("example-person"))

    if filtered:
        config = evolve(config, experience=Experience(disable=[JobSelector(title="Engineer", company="Example")]))

    profile = Profile("example-person", "Alex", sections=[Section("experience", "Experience", [group])])
    text = render_profile(profile, config, tmp_path).read_text().split(r"\begin{document}", 1)[1]
    assert text.count(r"\begin{roleprogression}") == 1
    company_heading = r"\entrytitle{\hypertarget{resumeme-section-0-job-0}{}Example}"
    current_heading = r"\roletitle{\hypertarget{resumeme-section-0-job-0-0}{}Staff Engineer}"
    previous_heading = r"\roletitle{\hypertarget{resumeme-section-0-job-0-1}{}Engineer}"
    assert text.count(current_heading) == 1
    assert text.count("Current delivery") == 1
    assert text.count(r"\includegraphics[") == 1
    assert "https://www.google.com/maps/search/" in text
    assert (previous_heading in text) is not filtered
    assert ("Earlier delivery" in text) is not filtered
    assert text.index(company_heading) < text.index(r"\begin{roleprogression}") < text.index(current_heading)
