"""
Keep signed-release ownership metadata out of generated profile text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from resumeme.compiler.asts.profile import Entry, Link, Profile, Section
from resumeme.compiler.passes.ownership import without_ownership_metadata
from resumeme.compiler.pipeline import render_profile
from resumeme.config import Config, LinkedIn

if TYPE_CHECKING:
    from pathlib import Path


def test_ownership_lines_are_removed_only_from_the_rendered_about_copy() -> None:
    """
    Remove signature lines and their links while preserving the source snapshot and personal text.

    Returns:
        None: Metadata is absent from the display copy but remains in source data and other sections.
    """
    release_url = "https://github.com/example/resumeme/releases"
    source = Profile(
        "example-person",
        "Alex Example",
        intro=["Staff platform engineer", "resume signature: SHA256:" + "a" * 64, "releases: " + release_url],
        sections=[
            Section(
                "about",
                "About",
                [
                    Entry(
                        "About",
                        ["Builds reliable platforms.", "RESUME SIGNATURE: SHA256:" + "a" * 64, "releases: " + release_url],
                        links=[Link("releases", release_url), Link("Portfolio", "https://example.org/")],
                    )
                ],
            ),
            Section("experience", "Experience", [Entry("SRE", ["Manage software releases."])]),
        ],
    )

    display = without_ownership_metadata(source)
    about = display.sections[0].entries[0]

    assert display.intro == ["Staff platform engineer"]
    assert about.paragraphs == ["Builds reliable platforms."]
    assert about.links == [Link("Portfolio", "https://example.org/")]
    assert display.sections[1] == source.sections[1]
    assert source.sections[0].entries[0].paragraphs[-2].startswith("RESUME SIGNATURE:")


def test_ownership_filter_preserves_nested_list_indentation() -> None:
    """
    Keep bullet nesting stable while removing a managed ownership line from About text.

    Returns:
        None: Leading spaces in retained list items survive the display-copy filter.
    """
    profile = Profile(
        "example-person",
        "Alex Example",
        sections=[
            Section(
                "about",
                "About",
                [Entry("About", ["- Platform work", "  - Nested work", "resume signature: SHA256:" + "a" * 64])],
            )
        ],
    )

    display = without_ownership_metadata(profile)

    assert display.sections[0].entries[0].paragraphs == ["- Platform work", "  - Nested work"]


def test_generated_tex_omits_published_identity_lines(tmp_path: Path) -> None:
    """
    Exclude LinkedIn's managed ownership block before LaTeX generation.

    Args:
        tmp_path (Path): Isolated compiler output directory.

    Returns:
        None: The rendered document keeps About prose and contains neither ownership field.
    """
    release_url = "https://github.com/example/resumeme/releases"
    profile = Profile(
        "example-person",
        "Alex Example",
        sections=[
            Section(
                "about",
                "About",
                [
                    Entry(
                        "About",
                        ["Builds reliable platforms.", "resume signature: SHA256:" + "a" * 64, "releases: " + release_url],
                    )
                ],
            )
        ],
    )
    config = Config(LinkedIn("example-person"), section_order=["about"])
    rendered = render_profile(profile, config, tmp_path).read_text(encoding="utf-8")

    assert "Builds reliable platforms." in rendered
    assert "resume signature:" not in rendered.casefold()
    assert release_url not in rendered
