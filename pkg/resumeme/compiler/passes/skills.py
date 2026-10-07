"""
Expand collapsed skill summaries using captured entry tags and reverse associations.
"""

from __future__ import annotations

import logging
import unicodedata
from collections import Counter
from typing import TYPE_CHECKING

from attrs import evolve

from resumeme.compiler.asts.profile import Skill
from resumeme.compiler.asts.sections import section_key
from resumeme.compiler.asts.skills import endorsement_count, skill_labels
from resumeme.compiler.constants.skills import COLLAPSED_SKILLS, SKILL_PREFIX
from resumeme.compiler.passes.experience import regroup_positions

if TYPE_CHECKING:
    from collections.abc import Iterator

    from resumeme.compiler.asts.profile import Entry, Profile

__all__ = ["expand_skill_summaries"]

_LOGGER = logging.getLogger(__name__)


def _key(value: str) -> str:
    """
    Compare captured names without changing punctuation or conflating similar titles.

    Args:
        value (str): Entry identity or skill label.

    Returns:
        str: Unicode-normalized, case-folded name with consistent whitespace.
    """
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _entries(entry: Entry) -> Iterator[Entry]:
    """
    Enumerate an entry and its nested positions for ambiguity detection.

    Args:
        entry (Entry): Visible source record.

    Yields:
        Entry: Parent followed by each descendant in source order.
    """
    yield entry

    for position in entry.positions:
        yield from _entries(position)


def _merge(skills: list[Skill]) -> list[Skill]:
    """
    Preserve first-observed spelling and order with the largest endorsement total.

    Args:
        skills (list[Skill]): Observed labels, potentially repeated across sources.

    Returns:
        list[Skill]: Unique named skills without summed endorsement counts.
    """
    result: dict[str, Skill] = {}

    for skill in skills:
        key = _key(skill.name)

        if key:
            previous = result.get(key, skill)
            result[key] = evolve(previous, endorsements=max(previous.endorsements, skill.endorsements))

    return list(result.values())


def _associations(profile: Profile) -> dict[str, list[Skill]]:
    """
    Resolve explicit Skills-section references to uniquely named visible entries.

    Args:
        profile (Profile): Filtered profile with consolidated projects.

    Returns:
        dict[str, list[Skill]]: Entry identity mapped to observed associated skills.
    """
    identities = Counter(
        _key(child.title)
        for section in profile.sections
        if section_key(section.key) != "skills"
        for entry in section.entries
        for child in _entries(entry)
        if child.title.strip()
    )
    result: dict[str, list[Skill]] = {}

    for section in profile.sections:
        if section_key(section.key) != "skills":
            continue

        for entry in section.entries:
            skills = entry.skills or ([Skill(entry.title, endorsement_count(entry.paragraphs))] if entry.title.strip() else [])

            # Match complete association rows, never a title mentioned incidentally inside prose or an ambiguous company name.
            references = {_key(line) for value in [*entry.paragraphs, *(link.label for link in entry.links)] for line in value.splitlines()}

            for reference in references:
                if identities[reference] == 1:
                    result.setdefault(reference, []).extend(skills)

    return result


def _expand_entry(entry: Entry, associations: dict[str, list[Skill]], *, hide_rows: bool) -> Entry:
    """
    Replace complete summary rows and their link labels without altering source records.

    Args:
        entry (Entry): Visible entry or grouped position.
        associations (dict[str, list[Skill]]): Skills explicitly linked to uniquely named entries.
        hide_rows (bool): Keep employment skill tags out of job prose.

    Returns:
        Entry: Expanded display copy; incomplete summaries remain intact with a diagnostic.
    """

    # Rewrite children before the flattened parent so tags cannot cross role boundaries.
    if entry.positions:
        entry = regroup_positions(entry, [_expand_entry(position, associations, hide_rows=hide_rows) for position in entry.positions])

    candidates = _merge([*entry.skills, *associations.get(_key(entry.title), [])])
    observed = list(entry.skills)
    replacements: dict[str, str] = {}

    def expand_line(line: str) -> str:
        """
        Resolve one collapsed row once, including repeated accessible link labels.

        Args:
            line (str): Source line with an optional trailing collapsed skill count.

        Returns:
            str: Named skills, unchanged unresolved text, or empty for hidden employment tags.
        """
        if line in replacements:
            return replacements[line]

        match = COLLAPSED_SKILLS.search(line)

        if match is None:
            return line

        visible = skill_labels(line)
        expanded = _merge([*visible, *candidates])
        missing = int(match["count"])
        available = len(expanded) - len({_key(skill.name) for skill in visible})
        replacement = line

        # Counts are only completeness checks. They cannot identify unknown names or justify guessing from unrelated skills.
        if available >= missing:
            prefix = "Skills: " if SKILL_PREFIX.match(line) else ""
            replacement = prefix + ", ".join(skill.name for skill in expanded)
        elif not hide_rows:
            _LOGGER.warning(
                "Cannot fully expand skill summary for %r: %s; only %d of %d hidden names captured. Refresh the profile capture.",
                entry.title,
                line,
                available,
                missing,
            )

        observed.extend(expanded)
        replacements[line] = "" if hide_rows else replacement
        return replacements[line]

    paragraphs: list[str] = []

    for paragraph in entry.paragraphs:
        lines = [expanded for line in paragraph.split("\n") if (expanded := expand_line(line)) or not line]
        value = "\n".join(lines)

        if value or not paragraph:
            paragraphs.append(value)

    title = expand_line(entry.title)
    links = [evolve(link, label=label) for link in entry.links if (label := expand_line(link.label)) or not link.label]

    return evolve(entry, title=title, paragraphs=paragraphs, links=links, skills=_merge(observed))


def expand_skill_summaries(profile: Profile) -> Profile:
    """
    Expand every captured skill summary before template rendering and word-cloud scoring.

    Args:
        profile (Profile): Visible profile after section/job exclusions and project consolidation.

    Returns:
        Profile: Display copy with evidence-backed skill names; the saved snapshot remains unchanged.
    """
    associations = _associations(profile)

    return evolve(
        profile,
        sections=[
            evolve(
                section,
                entries=[
                    _expand_entry(entry, associations, hide_rows=section_key(section.key) == "experience") for entry in section.entries
                ],
            )
            for section in profile.sections
        ],
    )
