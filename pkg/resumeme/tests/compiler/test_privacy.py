"""
Verify profile-location opt-out removes personal address fields without altering job locations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from resumeme.compiler.asts.profile import Entry, Link, Media, Profile, Section
from resumeme.compiler.passes.contact import prepare_contact
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


@pytest.mark.parametrize("label", ["Address", "Home address", "Mailing address", "Location"])
@pytest.mark.parametrize("inline", [False, True])
@pytest.mark.parametrize("address_first", [False, True])
def test_address_redaction_preserves_neighbors_in_flattened_contacts(label: str, inline: bool, address_first: bool) -> None:
    """
    Redact only the address field when LinkedIn combines email, websites, and addresses into one dialog entry.

    Args:
        label (str): Supported personal-address field label.
        inline (bool): Whether the field's first value shares its label line.
        address_first (bool): Whether the private field precedes other contact fields.

    Returns:
        None: Email, website, and phone survive while private text and references do not; source and repeated output are stable.
    """
    address = Link("123 Example Street", "https://www.google.com/maps/place/123+Example+Street/")
    website = Link("Portfolio", "https://example.org/alex")
    photo = Media("https://example.org/address.png", alt=address.label, link=address.url)
    values = [f"{label}: {address.label}"] if inline else [label, address.label]
    values.append("Apartment 4")
    other = ["Email", "alex@example.org", "Website", website.label]
    lines = [*(values + other if address_first else other + values), "Phone", "+1 555 0100"]
    entry = Entry(lines[0], ["\n".join(lines[1:])], links=[address, website], images=[photo])
    profile = Profile("example-person", "Alex Example", sections=[Section("contact", "Contact info", [entry])])
    cleaned = without_profile_location(profile)
    fields = prepare_contact(cleaned.sections[0].entries, display_websites=True)

    assert fields == [
        Entry("Email", ["alex@example.org"]),
        Entry("Website", [website.label], links=[website]),
        Entry("Phone", ["+1 555 0100"]),
    ]
    assert "123 Example Street" not in repr(cleaned)
    assert "Apartment 4" not in repr(cleaned)
    assert address.url not in repr(cleaned)
    assert photo.url not in repr(cleaned)
    assert without_profile_location(cleaned) == cleaned
    assert profile.sections[0].entries == [entry]


def test_flattened_contact_renders_email_with_location_disabled(tmp_path: Path) -> None:
    """
    Keep the clickable Email row when the address opt-out runs before contact normalization.

    Args:
        tmp_path (Path): Isolated template output directory.

    Returns:
        None: The PDF source retains the email destination and icon without personal address text.
    """
    entry = Entry("Your profile", ["linkedin.com/in/example-person", "Email", "alex@example.org", "Address", "123 Example Street"])
    profile = Profile("example-person", "Alex Example", sections=[Section("contact", "Contact info", [entry])])
    config = Config(LinkedIn(profile.username), section_order=["contact"], style=Style(display_location=False))
    source = render_profile(profile, config, tmp_path).read_text()

    assert r"\href{mailto:alex@example.org}{\makebox[1.3em][l]{\faEnvelope}\textbf{Email}}" in source
    assert "123 Example Street" not in source


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
