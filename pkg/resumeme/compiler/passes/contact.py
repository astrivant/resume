"""
Normalize contact fields and their references without changing the captured profile snapshot.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import quote

from attrs import evolve

from resumeme.compiler.asts.profile import Entry
from resumeme.compiler.constants.contact import BIRTHDAY as _BIRTHDAY
from resumeme.compiler.constants.contact import CONTACT_CONTROL as _CONTACT_CONTROL
from resumeme.compiler.constants.contact import CONTACT_FIELD as _CONTACT_FIELD
from resumeme.compiler.constants.contact import EMAIL_ADDRESS as _EMAIL_ADDRESS
from resumeme.compiler.constants.contact import PHONE_FIELDS, WEBSITE_FIELDS
from resumeme.compiler.constants.contact import PROFILE_FIELD as _PROFILE_FIELD
from resumeme.compiler.constants.contact import PROFILE_URL as _PROFILE_URL

if TYPE_CHECKING:
    from resumeme.compiler.asts.profile import Link

__all__ = ["contact_email_url", "is_contact_phone", "is_contact_website", "prepare_contact", "without_birthday"]


def is_contact_phone(entry: Entry) -> bool:
    """
    Identify a normalized Phone field.

    Args:
        entry (Entry): Contact field produced by the normalization pass.

    Returns:
        bool: Whether the field has a captured Phone or Phone number heading.
    """
    return entry.title.strip().casefold() in PHONE_FIELDS


def is_contact_website(entry: Entry) -> bool:
    """
    Identify a normalized Website field without treating social or email links as websites.

    Args:
        entry (Entry): Contact field produced by the normalization pass.

    Returns:
        bool: Whether the field has a captured Website or Websites heading.
    """
    return entry.title.strip().casefold() in WEBSITE_FIELDS


def contact_email_url(value: str) -> str:
    """
    Convert an observed email value into a mailto destination without adding inferred recipients or headers.

    Args:
        value (str): Value belonging to a captured Email field.

    Returns:
        str: Encoded mailto destination, or an empty string when the value is not a single email address.
    """
    address = value.strip()

    # Encode address punctuation as URI data so characters such as '?' cannot introduce mail headers.
    return "mailto:" + quote(address, safe="@.") if _EMAIL_ADDRESS.fullmatch(address) else ""


def _field_entry(title: str, values: list[str], links: list[Link]) -> Entry:
    """
    Retain a field's visible labels once and associate only its observed references.

    Args:
        title (str): Captured field heading, or empty for an unlabeled value.
        values (list[str]): Values in their captured order.
        links (list[Link]): Retained references belonging to the original contact entry.

    Returns:
        Entry: A field with owned links and redundant standalone destinations removed.
    """
    text = "\n".join([title, *values])
    owned = [link for link in links if any(label and label in text for label in (link.label, link.url, link.resolved_url))]
    ambiguous = {link.label for link in owned if len({item.resolved_url or item.url for item in owned if item.label == link.label}) > 1}

    # LinkedIn may capture a caption and its destination as separate nodes; retain the clickable caption, not a repeated URL row.
    redundant = {
        url
        for link in owned
        if link.label and link.label not in {link.url, link.resolved_url, *ambiguous} and any(link.label in line for line in values)
        for url in (link.url, link.resolved_url)
        if url
    }
    retained = list(dict.fromkeys(value for value in values if value not in redundant))

    # Ambiguous captions need their distinct URLs to remain selectable instead of losing both destinations.
    for link in owned:
        destination = link.resolved_url or link.url

        if link.label in ambiguous and destination not in retained:
            retained.append(destination)

    return Entry(title, retained, links=owned)


def prepare_contact(
    entries: list[Entry], *, display_birthday: bool = False, display_websites: bool = False, display_phone: bool = True
) -> list[Entry]:
    """
    Split flattened dialogs into contact fields and remove LinkedIn navigation and edit controls.

    Args:
        entries (list[Entry]): Captured contact blocks; both flattened dialogs and individual fields are accepted.
        display_birthday (bool): Whether birthday data may appear in the display copy.
        display_websites (bool): Whether captured Website fields and their references may appear in Contact.
        display_phone (bool): Whether captured Phone fields and their references may appear in Contact; email is always retained.

    Returns:
        list[Entry]: Ordered field/value entries with inline references, suitable for packaged and custom templates.
    """
    result: list[Entry] = []

    # Privacy filtering runs before regrouping so hidden dates cannot survive as labels, images, or orphaned links.
    for entry in entries if display_birthday else without_birthday(entries):
        links = [
            link
            for link in entry.links
            if not _CONTACT_CONTROL.fullmatch(link.label.strip())
            and not _PROFILE_FIELD.fullmatch(link.label.strip())
            and not any(_PROFILE_URL.match(value) for value in (link.url, link.resolved_url) if value)
        ]
        fields: list[Entry] = []
        title = ""
        values: list[str] = []
        hiding = False

        # Recognized field labels delimit a flattened dialog; unfamiliar values remain visible instead of being guessed away.
        for paragraph in [entry.title, *entry.paragraphs]:
            for raw in paragraph.splitlines():
                line = " ".join(raw.split())

                if not line or _CONTACT_CONTROL.fullmatch(line):
                    continue

                field = _CONTACT_FIELD.fullmatch(line)

                if field:
                    if title or values:
                        fields.append(_field_entry(title, values, links))

                    label = field["label"]
                    hiding = _PROFILE_FIELD.fullmatch(label) is not None
                    title = "" if hiding else label
                    values = [field["value"]] if not hiding and field["value"] else []
                elif not hiding and not _PROFILE_URL.match(line):
                    values.append(line)

        if title or values:
            fields.append(_field_entry(title, values, links))

        # Preserve linked-only contacts, but do not create a detached reference list for values already represented inline.
        used = {link for field in fields for link in field.links}
        fields.extend(Entry(paragraphs=[link.label or link.url], links=[link]) for link in links if link not in used)
        fields = [field for field in fields if field.paragraphs or field.links]
        images = [
            image
            for image in entry.images
            if not _PROFILE_URL.match(image.link) and not _CONTACT_CONTROL.fullmatch(image.alt) and not _PROFILE_FIELD.fullmatch(image.alt)
        ]

        if images:
            if not fields:
                fields.append(Entry())

            fields[0] = evolve(fields[0], images=images)

        # Filter complete fields after associating links and images, so hidden fields cannot return as orphaned references.
        result.extend(
            field
            for field in fields
            if (display_websites or not is_contact_website(field)) and (display_phone or not is_contact_phone(field))
        )

    return result


def without_birthday(entries: list[Entry]) -> list[Entry]:
    """
    Omit birthday fields from standalone entries and flattened LinkedIn contact dialogs.

    Args:
        entries (list[Entry]): Captured contact fields, with labels and values in source order.

    Returns:
        list[Entry]: Independent display entries with birthday text and its labeled references removed.
    """
    result: list[Entry] = []

    for entry in entries:
        retained: list[str] = []
        removed: set[str] = set()
        birthday_value: list[str] = []
        hiding = False

        # Legacy dialogs flatten multiple fields into one entry; the next contact label ends the birthday field.
        for paragraph in [entry.title, *entry.paragraphs]:
            for line in paragraph.splitlines():
                normalized = " ".join(line.split()).casefold()
                birthday = _BIRTHDAY.match(normalized)

                if birthday:
                    hiding = True
                    birthday_value = [normalized[birthday.end() :].strip()]
                    removed.update({"birthday", "date of birth"})
                elif _CONTACT_FIELD.match(normalized):
                    hiding = False
                elif hiding:
                    birthday_value.append(normalized)

                if hiding:
                    removed.add(normalized)

                    # Match reference labels against the date even when its month and day came from separate DOM nodes.
                    removed.add(" ".join(part for part in birthday_value if part))
                else:
                    retained.append(line)

        # Preserve entries with no birthday verbatim, including their paragraph boundaries and optional fields.
        if not removed:
            result.append(entry)
            continue

        # A linked date or birthday icon must not reappear in the reference list or image gallery.
        links = [link for link in entry.links if " ".join(link.label.split()).casefold() not in removed]
        hidden_urls = {link.url for link in entry.links if link not in links}
        images = [
            image for image in entry.images if " ".join(image.alt.split()).casefold() not in removed and image.link not in hidden_urls
        ]

        if retained:
            result.append(evolve(entry, title=retained[0], paragraphs=retained[1:], links=links, images=images))

    return result
