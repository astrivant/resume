"""
Verify birthday visibility without hiding neighboring contact fields or rewriting snapshots.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml
from attrs import evolve
from jsonschema import ValidationError

from resumeme.config import Config, LinkedIn, Style, load_config
from resumeme.latex.contact import without_birthday
from resumeme.latex.rendering import render_profile
from resumeme.models import Entry, Link, Media, Profile, Section

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    "lines",
    [
        ["Email", "alex@example.org", "Birthday", "November 25", "Website", "example.org"],
        ["Birthday", "November", "25", "Email", "alex@example.org", "Website", "example.org"],
        ["Email", "alex@example.org", "Website", "example.org", "Birthday", "November 25"],
        ["Email", "alex@example.org", "Birthday: November 25", "Website", "example.org"],
        ["Email", "alex@example.org", "BIRTHDAY\nNovember 25", "Website", "example.org"],
        ["Email", "alex@example.org", "Date of birth", "November 25", "Website", "example.org"],
    ],
)
def test_birthday_filter_preserves_neighboring_fields_and_snapshot(lines: list[str]) -> None:
    """
    Recognize flattened, split, and inline birthday fields in any contact-field position.

    Args:
        lines (list[str]): Captured contact lines containing the same retained email and website.

    Returns:
        None: Birthday text and linked media disappear only from the display copy.
    """
    website = Link("example.org", "https://example.org")
    birthday = Link("November 25", "https://example.org/birthday")
    image = Media("https://example.org/birthday.png", alt="Birthday", link=birthday.url)
    entry = Entry(lines[0], lines[1:], links=[website, birthday], images=[image])
    visible = without_birthday([entry])
    assert visible == [Entry("Email", ["alex@example.org", "Website", "example.org"], links=[website])]
    assert entry.title == lines[0]
    assert entry.paragraphs == lines[1:]
    assert entry.links == [website, birthday]
    assert entry.images == [image]


def test_birthday_only_entries_and_inline_contact_boundaries() -> None:
    """
    Remove empty birthday entries and retain subsequent inline contact fields.

    Returns:
        None: Minimal contacts and neighboring inline values retain their intended visibility.
    """
    assert without_birthday([]) == []
    assert without_birthday([Entry("Birthday", ["November 25"])]) == []
    assert without_birthday([Entry("Birthday: November 25", ["Email: alex@example.org"])]) == [Entry("Email: alex@example.org")]
    unrelated = Entry("Website", ["A birthday reminder service", "https://example.org"])
    assert without_birthday([unrelated]) == [unrelated]


@pytest.mark.parametrize("display", [False, True])
@pytest.mark.parametrize("disable_contact", [False, True])
def test_birthday_visibility_applies_to_packaged_and_custom_templates(tmp_path: Path, display: bool, disable_contact: bool) -> None:
    """
    Respect field and section visibility in every rendering path without touching unrelated prose.

    Args:
        tmp_path (Path): Isolated template and rendering directory.
        display (bool): Whether the birthday field is enabled.
        disable_contact (bool): Whether the entire contact section is disabled.

    Returns:
        None: Both template paths receive the same filtered contact data.
    """
    contact = Entry("Email", ["alex@example.org", "Birthday", "November 25"])
    profile = Profile(
        "example-person",
        "Alex",
        sections=[Section("contact-info", "Contact info", [contact]), Section("about", "About", [Entry("I build birthday reminders")])],
    )
    config = Config(LinkedIn(profile.username), style=Style(display_birthday=display), disable=["contact"] if disable_contact else [])
    custom = tmp_path / "custom.tex.j2"
    custom.write_text("((( profile.sections )))", encoding="utf-8")

    # Section exclusions still win when birthday display is enabled, including for user-provided templates.
    for template in (None, custom.name):
        source = render_profile(profile, evolve(config, template=template), tmp_path).read_text()
        assert ("November 25" in source) is (display and not disable_contact)
        assert ("alex@example.org" in source) is (not disable_contact)
        assert "I build birthday reminders" in source

    assert contact.paragraphs == ["alex@example.org", "Birthday", "November 25"]


@pytest.mark.parametrize("theme_value", [False, True])
def test_birthday_default_and_theme_precedence(tmp_path: Path, theme_value: bool) -> None:
    """
    Default omitted settings to false and allow explicit theme values to override the base style.

    Args:
        tmp_path (Path): Isolated configuration and render directory.
        theme_value (bool): Theme value opposing the explicit base style.

    Returns:
        None: Omitted configuration and both theme override directions render correctly.
    """
    path = tmp_path / "resumeme.config.yaml"
    path.write_text("linkedin:\n  username: example-person\n", encoding="utf-8")
    profile = Profile("example-person", "Alex", sections=[Section("contact", "Contact info", [Entry("Birthday", ["November 25"])])])
    config = load_config(path)
    assert config.style.display_birthday is False
    assert "November 25" not in render_profile(profile, config, tmp_path).read_text()
    path.write_text(
        yaml.safe_dump(
            {
                "linkedin": {"username": profile.username},
                "style": {
                    "display_birthday": not theme_value,
                    "theme": "custom",
                    "themes": {"custom": {"display_birthday": theme_value}},
                },
            }
        ),
        encoding="utf-8",
    )
    assert ("November 25" in render_profile(profile, load_config(path), tmp_path).read_text()) is theme_value


@pytest.mark.parametrize("theme", [False, True])
def test_birthday_setting_requires_boolean(tmp_path: Path, theme: bool) -> None:
    """
    Reject string booleans before cattrs can coerce a birthday visibility setting.

    Args:
        tmp_path (Path): Isolated configuration directory.
        theme (bool): Whether to validate a theme override instead of the base style.

    Returns:
        None: Both locations reject the invalid configuration.
    """
    override = {"display_birthday": "false"}
    style = {"themes": {"custom": override}} if theme else override
    path = tmp_path / "resumeme.config.yaml"
    path.write_text(yaml.safe_dump({"linkedin": {"username": "example-person"}, "style": style}), encoding="utf-8")

    with pytest.raises(ValidationError):
        load_config(path)
