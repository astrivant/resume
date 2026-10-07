"""
Define the lossless text, link, and image records shared by capture and rendering.
"""

from __future__ import annotations

import json
from importlib.resources import files
from typing import TYPE_CHECKING

import cattrs
from attrs import field, frozen
from jsonschema import Draft202012Validator

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["Entry", "Link", "Media", "Profile", "Section", "Skill", "load_profile", "save_profile"]


@frozen
class Link:
    """
    Retain the display label and destination of a profile or project link.

    Attributes:
        label (str): Text displayed beside the destination.
        url (str): Absolute HTTP(S) destination.
    """

    label: str
    url: str


@frozen
class Media:
    """
    Reference a downloaded image, its accessible label, and its optional link.

    Attributes:
        url (str): Original remote image URL.
        alt (str): Accessible description from the profile.
        path (str): Portable PNG path, empty until downloaded.
        link (str): Destination opened by clicking this image, if any.
    """

    url: str
    alt: str = ""
    path: str = ""
    link: str = ""


@frozen
class Skill:
    """
    Retain a named skill or tag and its observed endorsement total.

    Attributes:
        name (str): Display spelling, including multiword skills and punctuation.
        endorsements (int): Observed total, never summed across duplicate observations.
    """

    name: str
    endorsements: int = 0


@frozen
class Entry:
    """
    Preserve an entry's full text and associated media without a length limit.

    Attributes:
        title (str): First displayed line or entry heading.
        paragraphs (list[str]): Remaining text in display order.
        links (list[Link]): References associated with this entry.
        images (list[Media]): Logos, figures, and linked project previews.
        skills (list[Skill]): Structured skill declarations or associations, including hidden job tags.
        positions (list[Entry]): Individual roles within grouped employment; the parent retains the complete flattened content.
    """

    title: str = ""
    paragraphs: list[str] = field(factory=list)
    links: list[Link] = field(factory=list)
    images: list[Media] = field(factory=list)
    skills: list[Skill] = field(factory=list)
    positions: list[Entry] = field(factory=list)


@frozen
class Section:
    """
    Keep profile sections in their displayed order, including unfamiliar sections.

    Attributes:
        key (str): Section anchor or detail-route identifier.
        title (str): Display heading.
        entries (list[Entry]): Complete ordered section content.
    """

    key: str
    title: str
    entries: list[Entry] = field(factory=list)


@frozen
class Profile:
    """
    Own a portable snapshot; warnings record capture or asset incompleteness.

    Attributes:
        username (str): LinkedIn owner slug used to prevent cross-owner builds.
        name (str): Display name from the profile heading.
        intro (list[str]): Introductory text in source order.
        images (list[Media]): Profile photo and banner references.
        links (list[Link]): Introductory contact and profile references.
        sections (list[Section]): Expanded profile sections.
        warnings (list[str]): Conditions requiring explicit acceptance before rendering.
        captured_at (str): UTC capture time for provenance, excluded from the PDF.
        schema_version (int): Snapshot format version.
    """

    username: str
    name: str
    intro: list[str] = field(factory=list)
    images: list[Media] = field(factory=list)
    links: list[Link] = field(factory=list)
    sections: list[Section] = field(factory=list)
    warnings: list[str] = field(factory=list)
    captured_at: str = ""
    schema_version: int = 1


_converter = cattrs.Converter(forbid_extra_keys=True)


def load_profile(path: Path, username: str) -> Profile:
    """
    Validate a snapshot and ensure forks cannot render the previous owner's data.

    Args:
        path (Path): Snapshot to read.
        username (str): Expected LinkedIn username from the local configuration.

    Returns:
        Profile: Validated snapshot.

    Raises:
        ValueError: The snapshot belongs to another username.
        jsonschema.ValidationError: The snapshot does not satisfy the schema.
    """

    # The snapshot is a portable interchange format; reject malformed fields before constructing typed records.
    raw = json.loads(path.read_text(encoding="utf-8"))
    schema = json.loads(files("resume").joinpath("resources/profile.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(raw)
    profile = _converter.structure(raw, Profile)

    # Ownership is independent of schema validity: a valid snapshot can still belong to the upstream fork.
    if profile.username.casefold() != username.casefold():
        raise ValueError("Snapshot username differs from configuration. Run `resume capture` for the new owner.")

    return profile


def save_profile(profile: Profile, path: Path) -> None:
    """
    Atomically publish a snapshot after collection completes.

    Args:
        profile (Profile): Snapshot without browser credentials.
        path (Path): Destination relative to the configuration directory.

    Returns:
        None: The serialized snapshot is written to disk.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    # Publish with a same-directory rename so interrupted serialization cannot truncate the accepted snapshot.
    pending = path.with_suffix(".pending.json")
    pending.write_text(json.dumps(_converter.unstructure(profile), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pending.replace(path)
