"""
Verify profile-location opt-out removes personal address fields without altering job locations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from resumeme.compiler.asts.profile import Entry, Profile, Section
from resumeme.compiler.passes.privacy import without_profile_location
from resumeme.compiler.pipeline import render_profile
from resumeme.config import Config, LinkedIn, Style

if TYPE_CHECKING:
    from pathlib import Path


def test_profile_location_opt_out_keeps_pronouns_prose_and_employment_places() -> None:
    """
    Remove a geographic profile line and personal Address field while preserving resume content.

    Returns:
        None: Only personal profile-location data is removed from the returned copy.
    """
    contact = Section(
        "contact",
        "Contact info",
        [Entry("Address", ["123 Example Street"]), Entry("Email", ["alex@example.org"])],
    )
    experience = Section("experience", "Experience", [Entry("Staff Engineer", ["Boston, MA · Remote"])])
    profile = Profile(
        "example-person",
        "Alex Example",
        intro=["She/Her", "Staff Engineer", "Atlanta Metropolitan Area", "Open to work"],
        headline="Staff Engineer",
        sections=[contact, experience],
    )

    sanitized = without_profile_location(profile)

    assert sanitized.intro == ["She/Her", "Staff Engineer", "Open to work"]
    assert sanitized.sections[0].entries == [Entry("Email", ["alex@example.org"])]
    assert sanitized.sections[1] == experience
    assert "Atlanta Metropolitan Area" in profile.intro
    assert profile.sections[0] == contact


def test_resume_render_hides_profile_location_but_keeps_job_locations(tmp_path: Path) -> None:
    """
    Apply the location setting in the compiler while preserving geographic job metadata.

    Args:
        tmp_path (Path): Isolated LaTeX output directory.

    Returns:
        None: Personal location is absent from the rendered source while the role's location remains.
    """
    profile = Profile(
        "example-person",
        "Alex Example",
        intro=["Atlanta Metropolitan Area"],
        sections=[Section("experience", "Experience", [Entry("Staff Engineer", ["Boston, MA · Remote"])])],
    )
    config = Config(
        LinkedIn(profile.username),
        style=Style(display_location=False),
        section_order=["experience"],
    )

    source = render_profile(profile, config, tmp_path, allow_incomplete=True).read_text(encoding="utf-8")

    assert "Atlanta Metropolitan Area" not in source
    assert "Boston, MA" in source
