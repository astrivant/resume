"""
Separate attached project descriptions from flattened employment text using observed card captions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from resumeme.compiler.asts.dates import employment_period

if TYPE_CHECKING:
    from resumeme.compiler.asts.profile import Entry

__all__ = ["partition_descriptions"]


def partition_descriptions(entry: Entry, captions: dict[str, set[str]]) -> tuple[list[str], dict[str, list[str]]]:
    """
    Move text following an unambiguous attachment caption until the next card or role boundary.

    LinkedIn flattens each attachment into its title followed by description lines.
    Only observed, standalone card labels establish ownership; inline references
    and text before the first card remain ordinary employment prose.

    Args:
        entry (Entry): Employment display copy with attachment captions still in its paragraphs.
        captions (dict[str, set[str]]): Attachment identities mapped to their observed title and link labels.

    Returns:
        tuple[list[str], dict[str, list[str]]]: Retained employment text and descriptions keyed by attachment identity.
    """
    owners: dict[str, set[str]] = {}

    for identity, labels in captions.items():
        for label in labels:
            if label.strip():
                owners.setdefault(" ".join(label.split()).casefold(), set()).add(identity)

    remaining: list[str] = []
    descriptions: dict[str, list[str]] = {}
    role_titles = {position.title for position in entry.positions}
    active: str | None = None

    for index, line in enumerate(entry.paragraphs):
        key = " ".join(line.split()).casefold()
        following = entry.paragraphs[index + 1] if index + 1 < len(entry.paragraphs) else ""

        # A flattened legacy company can introduce another role after its attachment list; keep that role's title and dates.
        if (
            line in role_titles
            or employment_period(line)
            or employment_period(following)
            or key.rstrip(":") in {"responsibilities", "technologies", "projects", "skills"}
        ):
            active = None
            remaining.append(line)
        elif key in owners:
            # Shared labels cannot identify a specific project; retain ambiguous text rather than assigning it arbitrarily.
            matches = owners[key]
            active = next(iter(matches)) if len(matches) == 1 else None

            if active is None:
                remaining.append(line)
        elif active is not None:
            descriptions.setdefault(active, []).append(line)
        else:
            remaining.append(line)

    return remaining, descriptions
