"""
Verify tri-state sidebar employment selection without restoring filtered body content.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml
from attrs import evolve
from jsonschema import ValidationError
from PIL import Image

from resumeme.compiler.asts.presentation import HeaderPosition
from resumeme.compiler.asts.profile import Entry, Media, Profile, Section
from resumeme.compiler.passes.header import prepare_header_position
from resumeme.compiler.pipeline import render_profile
from resumeme.config import Config, Experience, JobSelector, LinkedIn, Style, load_config

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("display", [None, True, False])
@pytest.mark.parametrize("filter_kind", ["job", "dates", "section", "all"])
def test_current_position_respects_tristate_and_filtered_assets(tmp_path: Path, display: bool | None, filter_kind: str) -> None:
    """
    Select header identity from the intended profile while excluded attachments and descriptions remain absent.

    Args:
        tmp_path (Path): Isolated rendering root.
        display (bool | None): Effective sidebar employment policy.
        filter_kind (str): Exclusion or date window that removes the captured first role from Experience.

    Returns:
        None: Packaged and custom templates share the selected identity, with source data and visible body roles preserved.
    """
    Image.new("RGB", (20, 20), "red").save(tmp_path / "first.png")
    Image.new("RGB", (20, 20), "blue").save(tmp_path / "second.png")
    first_logo = Media(
        "https://example.org/company-logo-first.png", alt="First Co logo", path="first.png", link="https://example.org/first"
    )
    second_logo = Media("https://example.org/company-logo-second.png", alt="Second Co logo", path="second.png")
    excluded = Entry(
        "Founder",
        ["First Co", "2026 - Present", "Excluded description"],
        images=[
            first_logo,
            Media("https://example.org/private.png", path="missing-private.png"),
        ],
    )
    retained = Entry("Staff Engineer", ["Second Co", "2023 - 2025", "Retained description"], images=[second_logo])
    profile = Profile(
        "example-person",
        "Alex",
        intro=["They/Them", "First Co", "Boston", "First Co"],
        images=[first_logo],
        sections=[Section("experience", "Experience", [excluded, retained])],
    )
    original = repr(profile)
    config = Config(LinkedIn(profile.username), style=Style(display_current_position=display, profile_column_side="right"))

    if filter_kind == "job":
        config = evolve(config, experience=Experience(disable=[JobSelector(company="First Co")]))
    elif filter_kind == "dates":
        config = evolve(config, experience=Experience(since="2023-01-01", as_of="2025-12-31"))
    elif filter_kind == "section":
        config = evolve(config, section_order=["contact"])
    else:
        config = evolve(config, experience=Experience(disable=[JobSelector(company="First Co"), JobSelector(company="Second Co")]))

    expected = "First Co" if display is True else "Second Co" if display is None and filter_kind in {"job", "dates"} else None
    expected_title = "Founder" if expected == "First Co" else "Staff Engineer" if expected else None
    source = render_profile(profile, config, tmp_path).read_text()
    identity = source.split(r"\begin{document}", 1)[1].split(r"\identityheading{Contact}", 1)[0]
    assert ("First Co" in identity) is (expected == "First Co")
    assert ("Second Co" in identity) is (expected == "Second Co")
    assert ("Founder" in identity) is (expected_title == "Founder")
    assert ("Staff Engineer" in identity) is (expected_title == "Staff Engineer")
    assert "Boston" in identity and "They/Them" in identity
    assert "Excluded description" not in source and "missing-private" not in source
    assert ("Retained description" in source) is (filter_kind in {"job", "dates"})

    # Custom templates receive no stale header company or source assets, even when the explicit opt-in ignores body filters.
    template = tmp_path / "custom.tex.j2"
    template.write_text("((( profile.intro )))|((( profile.images )))|((( current_position )))")
    custom = render_profile(profile, evolve(config, template=template.name), tmp_path).read_text()
    intro, images, position = custom.split("|", 2)
    assert "First Co" not in intro and images == "[]"
    assert (position != "None") is (expected is not None)

    if expected:
        assert f"company='{expected}'" in position and f"title='{expected_title}'" in position
        assert "assets/" in position and "missing-private" not in position

    assert repr(profile) == original


@pytest.mark.parametrize("structured", [False, True])
def test_grouped_positions_use_first_retained_role(structured: bool) -> None:
    """
    Select nested role titles rather than treating their employer heading as the job title.

    Args:
        structured (bool): Whether the capture has explicit nested role metadata or legacy flattened text.

    Returns:
        None: The first retained title and shared employer are used without dates or descriptions entering the sidebar.
    """
    roles = [Entry("Staff Engineer", ["2025 - Present", "New responsibilities"]), Entry("Engineer", ["2020 - 2025", "Earlier work"])]
    group = Entry(
        "Example Co",
        ["Full-time", *(line for role in roles for line in [role.title, *role.paragraphs])],
        positions=roles if structured else [],
    )
    profile = Profile("example-person", "Alex", sections=[Section("experience", "Experience", [group])])
    _, selected = prepare_header_position(profile, captured=profile, display=None)
    assert selected == HeaderPosition("Staff Engineer", "Example Co")

    # Simulate the already-filtered display tree, preserving the original capture for the explicit unfiltered policy.
    retained = evolve(group, paragraphs=["Full-time", roles[1].title, *roles[1].paragraphs], positions=[roles[1]])
    visible = evolve(profile, sections=[Section("experience", "Experience", [retained])])
    assert prepare_header_position(visible, captured=profile, display=None)[1] == HeaderPosition("Engineer", "Example Co")
    assert prepare_header_position(visible, captured=profile, display=True)[1] == selected


@pytest.mark.parametrize("display", [None, True, False])
def test_minimal_identity_and_missing_employer_are_supported(display: bool | None) -> None:
    """
    Handle empty Experience and title-only roles without inferring an employer or removing location and pronouns.

    Args:
        display (bool | None): Sidebar employment policy.

    Returns:
        None: Minimal identity remains intact and incomplete employment emits only observed fields.
    """
    profile = Profile("example-person", "Alex", intro=["They/Them", "Boston"])
    assert prepare_header_position(profile, captured=profile, display=display) == (profile, None)
    profile = evolve(profile, sections=[Section("experience", "Experience", [Entry("Engineer")])])
    expected = HeaderPosition("Engineer") if display is not False else None
    assert prepare_header_position(profile, captured=profile, display=display) == (profile, expected)


@pytest.mark.parametrize("display", [None, True, False])
def test_current_position_theme_precedence_and_default(tmp_path: Path, display: bool | None) -> None:
    """
    Accept all three YAML values and let an explicit null theme override restore filtered selection.

    Args:
        tmp_path (Path): Isolated configuration and render directory.
        display (bool | None): Theme override, including null as a meaningful value.

    Returns:
        None: Theme values control selection and an omitted setting defaults to filtered employment.
    """
    path = tmp_path / "resumeme.config.yaml"
    path.write_text("linkedin: {username: example-person}\n")
    assert load_config(path).style.display_current_position is None
    path.write_text(
        yaml.safe_dump(
            {
                "linkedin": {"username": "example-person"},
                "experience": {"disable": [{"title": "Founder"}]},
                "style": {
                    "display_current_position": True if display is None else None,
                    "theme": "custom",
                    "themes": {"custom": {"display_current_position": display}},
                },
            }
        )
    )
    profile = Profile("example-person", "Alex", sections=[Section("experience", "Experience", [Entry("Founder"), Entry("Engineer")])])
    template = tmp_path / "custom.tex.j2"
    template.write_text("((( current_position.title if current_position else 'hidden' )))")
    config = evolve(load_config(path), template=template.name)
    assert render_profile(profile, config, tmp_path).read_text() == (
        "Founder" if display is True else "Engineer" if display is None else "hidden"
    )


@pytest.mark.parametrize("theme", [False, True])
@pytest.mark.parametrize("value", ["false", "null", 1])
def test_current_position_config_rejects_nonboolean_values(tmp_path: Path, theme: bool, value: str | int) -> None:
    """
    Reject coercible strings and numbers for both base settings and inline themes.

    Args:
        tmp_path (Path): Isolated configuration directory.
        theme (bool): Whether the invalid value is a theme override.
        value (str | int): Invalid YAML value.

    Returns:
        None: Configuration validation fails before rendering.
    """
    settings = {"display_current_position": value}
    path = tmp_path / "resumeme.config.yaml"
    path.write_text(
        yaml.safe_dump({"linkedin": {"username": "example-person"}, "style": {"themes": {"custom": settings}} if theme else settings})
    )

    with pytest.raises(ValidationError):
        load_config(path)
