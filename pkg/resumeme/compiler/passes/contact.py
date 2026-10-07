"""
Filter optional contact fields without changing the captured profile snapshot.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from attrs import evolve

from resumeme.compiler.constants.contact import BIRTHDAY as _BIRTHDAY
from resumeme.compiler.constants.contact import CONTACT_FIELD as _CONTACT_FIELD

if TYPE_CHECKING:
    from resumeme.compiler.asts.profile import Entry

__all__ = ["without_birthday"]


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
