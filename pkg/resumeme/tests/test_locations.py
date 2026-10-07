"""
Verify clickable job geography without changing source text or linking descriptions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit

import pytest

from resumeme.compiler.asts.profile import Entry, Profile, Section
from resumeme.compiler.passes.locations import job_locations
from resumeme.compiler.pipeline import render_profile
from resumeme.config import Config, Experience, JobSelector, LinkedIn

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    "location",
    [
        "Atlanta, Georgia, United States",
        "Boston, Massachusetts, United States · Hybrid",
        "Wakefield, Massachusetts, United States · Remote",
        "Rochester, New York Metropolitan Area · On-site",
        "London",
        "New York",
        "São Paulo, Brazil",
        "Rio de Janeiro, Brazil",
        "東京, 日本",
        "St. John's, Newfoundland & Labrador, Canada",
    ],
)
def test_job_location_queries_keep_geography_and_omit_work_modes(location: str) -> None:
    """
    Encode local and international place names without including employment arrangements.

    Args:
        location (str): Captured employment metadata with an optional work-mode suffix.

    Returns:
        None: The map query round-trips to the captured place and source paragraphs stay unchanged.
    """
    paragraphs = ["Example Co · Full-time", "Jan 2020 - Present · 6 yrs", location, "Built services"]
    entry = Entry("Engineer", paragraphs)
    link = job_locations(entry)[location]
    place = location.split("·", 1)[0].strip()
    destination = urlsplit(link.url)
    assert destination.scheme == "https"
    assert destination.netloc == "www.google.com"
    assert destination.path == "/maps/search/"
    assert parse_qs(destination.query) == {"api": ["1"], "query": [place]}
    assert link.label == place
    assert entry.paragraphs == paragraphs


@pytest.mark.parametrize(
    "line",
    [
        "Remote",
        "Hybrid",
        "On-site",
        "Responsibilities",
        "Projects:",
        "Built systems in Boston, Massachusetts",
        "- Worked in Atlanta, Georgia",
        "Led engineering teams.",
        "https://example.org/Boston",
        r"Boston \input{secret}",
        "2020 - Present",
        "",
    ],
)
def test_absent_locations_do_not_turn_job_prose_into_map_links(line: str) -> None:
    """
    Reject headings, work modes, links, and prose occupying an omitted location's metadata slot.

    Args:
        line (str): Non-location content immediately following employment dates.

    Returns:
        None: Incomplete or location-free jobs do not acquire invented geography.
    """
    assert job_locations(Entry("Engineer", ["Example Co", "2020 - Present", line])) == {}
    assert job_locations(Entry("Engineer")) == {}


def test_grouped_company_locations_and_role_locations_are_recognized() -> None:
    """
    Keep shared company geography separate from each role's work arrangement and location.

    Returns:
        None: Legacy and structured groups expose the same shared and role-specific destinations.
    """
    role = Entry("Engineer", ["2020 - Present", "Remote", "Built services"])
    earlier = Entry("Intern", ["2019 - 2020", "Medina, New York, United States · On-site"])
    lines = ["Full-time · 7 yrs", "Boston, Massachusetts, United States", role.title, *role.paragraphs, earlier.title, *earlier.paragraphs]

    for positions in ([], [role, earlier]):
        locations = job_locations(Entry("Example Co", lines, positions=positions))
        assert list(locations) == ["Boston, Massachusetts, United States", "Medina, New York, United States · On-site"]


def test_rendered_locations_escape_links_and_respect_job_filters(tmp_path: Path) -> None:
    """
    Render inline map links only for retained experience, preserving suffixes and surrounding content.

    Args:
        tmp_path (Path): Isolated rendering directory.

    Returns:
        None: Dates, descriptions, other sections, and captured records are preserved without duplicate reference rows.
    """
    place = "Newfoundland & Labrador, Canada"
    role = Entry("Engineer", ["Example Co", "2020 - Present", place + " · Hybrid", "Built services"])
    omitted = Entry("Intern", ["Another Co", "2018 - 2019", "Atlanta, Georgia, United States"])
    profile = Profile(
        "example-person",
        "Alex",
        sections=[Section("experience", "Experience", [role, omitted]), Section("education", "Education", [role])],
    )
    config = Config(LinkedIn(profile.username), experience=Experience(disable=[JobSelector(title="Intern")]))
    source = render_profile(profile, config, tmp_path).read_text()
    assert source.count("https://www.google.com/maps/search/") == 1
    assert r"\href{https://www.google.com/maps/search/?api=1\&query=Newfoundland+\%26+Labrador\%2C+Canada}" in source
    assert r"{Newfoundland \& Labrador, Canada} · Hybrid}" in source
    assert r"\profileparagraph{2020 - Present}" in source
    assert "Built services" in source
    assert "Atlanta" not in source
    assert role.paragraphs[2] == place + " · Hybrid"
    assert role.links == []
