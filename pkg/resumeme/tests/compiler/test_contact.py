"""
Verify normalized contact fields, inline links, and birthday visibility without rewriting snapshots.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml
from attrs import evolve
from jsonschema import ValidationError

from resumeme.compiler.asts.profile import Entry, Link, Media, Profile, Section
from resumeme.compiler.backends.latex.escaping import latex_contact_text
from resumeme.compiler.constants.sections import DEFAULT_SECTION_ORDER
from resumeme.compiler.passes.contact import contact_email_url, prepare_contact, without_birthday
from resumeme.compiler.pipeline import render_profile
from resumeme.config import Config, LinkedIn, Style, load_config

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("display_birthday", [False, True])
@pytest.mark.parametrize("structured", [False, True])
def test_contact_pass_groups_fields_and_removes_navigation(display_birthday: bool, structured: bool) -> None:
    """
    Normalize current and legacy contact captures without losing neighboring values or observed link targets.

    Args:
        display_birthday (bool): Whether a captured birthday is visible.
        structured (bool): Whether each field already has its own captured entry.

    Returns:
        None: Only useful contact fields and their references survive, with the input snapshot unchanged.
    """
    website = Link("Portfolio & writing", "https://lnkd.in/portfolio", "https://example.org/alex")
    profile = Link("linkedin.com/in/alex", "https://www.linkedin.com/in/alex/")
    edit = Link("Edit contact info", "https://www.linkedin.com/in/alex/overlay/edit/contact-info/")
    fields = [
        Entry("Your profile", [profile.label], links=[profile]),
        Entry("Website", [website.label, website.url], links=[website]),
        Entry("Email", ["alex@example.org"]),
        Entry("Birthday", ["November 25"]),
        Entry("Phone", ["+1 555 0100 (Mobile)"]),
        Entry("Edit contact info", links=[edit]),
    ]
    lines = [line for field in fields for line in [field.title, *field.paragraphs]]
    entries = fields if structured else [Entry(lines[0], lines[1:], links=[profile, website, edit])]
    original = repr(entries)
    expected = [Entry("Website", [website.label], links=[website]), Entry("Email", ["alex@example.org"])]

    if display_birthday:
        expected.append(Entry("Birthday", ["November 25"]))

    expected.append(Entry("Phone", ["+1 555 0100 (Mobile)"]))
    assert prepare_contact(entries, display_birthday=display_birthday, display_websites=True) == expected
    assert repr(entries) == original
    assert prepare_contact(expected, display_birthday=display_birthday, display_websites=True) == expected


def test_inline_contacts_empty_dialogs_and_link_only_values() -> None:
    """
    Preserve multiple websites and unfamiliar values while dropping empty labels and navigation-only captures.

    Returns:
        None: Sparse, inline, and URL-only inputs retain usable contact information without guessed fields.
    """
    assert prepare_contact([]) == []
    assert prepare_contact([Entry("LinkedIn profile", ["linkedin.com/in/alex", "Edit contact info"])]) == []
    assert prepare_contact([Entry("Website")]) == []
    site = Link("Portfolio", "https://example.org/alex")
    assert prepare_contact([Entry(links=[site])]) == [Entry(paragraphs=["Portfolio"], links=[site])]
    assert prepare_contact([Entry("Email: alex@example.org", ["Phone: +1 555 0100", "Timezone: UTC"])]) == [
        Entry("Email", ["alex@example.org"]),
        Entry("Phone", ["+1 555 0100", "Timezone: UTC"]),
    ]
    domains = [Link("example.org", "https://example.org/alex"), Link("work.example.org", "https://work.example.org/alex")]
    assert prepare_contact(
        [Entry("Websites", ["example.org (Personal)", "work.example.org (Company)"], links=domains)], display_websites=True
    ) == [Entry("Websites", ["example.org (Personal)", "work.example.org (Company)"], links=domains)]


def test_website_and_phone_visibility_are_independent_and_email_is_retained() -> None:
    """
    Apply Website and Phone switches independently while keeping Email in the contact contract.

    Returns:
        None: Each disabled field disappears without affecting the other field or Email.
    """
    entries = [
        Entry("Website", ["example.org"]),
        Entry("Phone", ["+1 555 0100"]),
        Entry("Email", ["alex@example.org"]),
    ]

    assert prepare_contact(entries, display_websites=False, display_phone=False) == [Entry("Email", ["alex@example.org"])]
    assert prepare_contact(entries, display_websites=True, display_phone=False) == [
        Entry("Website", ["example.org"]),
        Entry("Email", ["alex@example.org"]),
    ]
    assert prepare_contact(entries, display_websites=False, display_phone=True) == [
        Entry("Phone", ["+1 555 0100"]),
        Entry("Email", ["alex@example.org"]),
    ]


def test_contact_links_are_inline_escaped_and_unambiguous() -> None:
    """
    Link exact observed captions and complete URLs without matching domain substrings inside email addresses.

    Returns:
        None: Captions preserve their targets and TeX escaping, with ambiguous links retained as distinct URLs.
    """
    link = Link("Portfolio & writing", "https://lnkd.in/portfolio", "https://example.org/a_b?x=1&y=2")
    assert latex_contact_text("Portfolio & writing (Personal)", [link]) == (
        r"\href{https://example.org/a\_b?x=1\&y=2}{Portfolio \& writing} (Personal)"
    )
    domain = Link("example.org", "https://example.org/alex")
    assert latex_contact_text("alex@example.org", [domain]) == "alex@example.org"
    assert latex_contact_text("https://example.org/alex", [domain]).startswith(r"\href{https://example.org/alex}{https:")
    ambiguous = [Link("Portfolio", "https://one.example.org"), Link("Portfolio", "https://two.example.org")]
    field = prepare_contact([Entry("Website", ["Portfolio"], links=ambiguous)], display_websites=True)[0]
    assert field.paragraphs == ["Portfolio", "https://one.example.org", "https://two.example.org"]
    assert latex_contact_text("Portfolio", field.links) == "Portfolio"


def test_contact_rendering_uses_labels_once_and_custom_templates_receive_clean_fields(tmp_path: Path) -> None:
    """
    Render a captured website beside its field label and keep filtered source data available to custom backends.

    Args:
        tmp_path (Path): Isolated template and output directory.

    Returns:
        None: Packaged output has no detached reference rows, and custom templates receive normalized contacts.
    """
    website = Link("linktr.ee", "https://linktr.ee/example-person")
    lines = ["linkedin.com/in/example-person", "Website", "linktr.ee (Other)", "Email", "alex@example.org", "Edit contact info"]
    entry = Entry("Your profile", lines, links=[website])
    profile = Profile("example-person", "Alex", sections=[Section("contact-info", "Contact info", [entry])])
    config = Config(LinkedIn(profile.username), style=Style(display_websites=True))
    source = render_profile(profile, config, tmp_path).read_text()
    assert r"\profileparagraph{\textbf{Website}: \href{https://linktr.ee/example-person}{linktr.ee} (Other)}" in source
    assert r"\href{mailto:alex@example.org}{\makebox[1.3em][l]{\faEnvelope}\textbf{Email}}" in source
    assert source.count("alex@example.org") == 1
    assert source.count("https://linktr.ee/example-person") == 1
    assert "Edit contact info" not in source
    assert "Your profile" not in source
    assert "Contact info" not in source
    custom = tmp_path / "contact.tex.j2"
    custom.write_text("((( profile.sections )))")
    display = render_profile(profile, evolve(config, template=custom.name), tmp_path).read_text()
    assert "title='Contact'" in display and "title='Website'" in display
    assert "Edit contact info" not in display and "Your profile" not in display
    assert "https://linktr.ee/example-person" in display


@pytest.mark.parametrize(
    "address, expected",
    [
        ("alex@example.org", "mailto:alex@example.org"),
        (" alex+jobs@example.org ", "mailto:alex%2Bjobs@example.org"),
        ("alex?subject=hello@example.org", "mailto:alex%3Fsubject%3Dhello@example.org"),
        ("Email unavailable", ""),
        ("alex@example.org\nBcc: another@example.org", ""),
    ],
)
def test_email_destinations_preserve_addresses_without_mail_headers(address: str, expected: str) -> None:
    """
    Encode single captured addresses and retain unsupported values as text instead of making invalid links.

    Args:
        address (str): Captured contact field value.
        expected (str): Expected mailto URI or empty fallback.

    Returns:
        None: Address punctuation cannot introduce message headers or extra recipients.
    """
    assert contact_email_url(address) == expected


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
    config = Config(
        LinkedIn(profile.username),
        style=Style(display_birthday=display),
        section_order=[key for key in DEFAULT_SECTION_ORDER if key not in (["contact"] if disable_contact else [])],
    )
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
