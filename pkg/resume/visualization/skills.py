"""
Aggregate skill references and endorsements into deterministic, auditable word clouds.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from importlib.resources import files
from io import BytesIO
from math import sqrt
from typing import TYPE_CHECKING

from attrs import frozen
from wordcloud import WordCloud

from resume.linkedin.sections import section_key
from resume.linkedin.skills import endorsement_count
from resume.models import Skill

if TYPE_CHECKING:
    from pathlib import Path

    from resume.models import Profile

__all__ = ["SkillScore", "render_skill_cloud", "skill_scores"]

_HASHTAG = re.compile(r"(?<!\w)#([^\W\d]\w*)", re.UNICODE)


@frozen
class SkillScore:
    """
    Explain the contribution of text references and observed endorsements to a skill.

    Attributes:
        references (int): Whole-phrase occurrences and otherwise unrepresented explicit tags.
        endorsements (int): Highest observed total for this skill, deduplicated across observations.
    """

    references: int
    endorsements: int

    @property
    def weight(self) -> int:
        """
        Weight each observed endorsement as two additional references.

        Returns:
            int: References plus twice the observed endorsement count.
        """
        return self.references + 2 * self.endorsements


def _normalized(value: str) -> str:
    """
    Normalize Unicode, case, and spacing without stripping meaningful skill punctuation.

    Args:
        value (str): Skill label or profile text.

    Returns:
        str: Comparable text with C++, C#, and multiword labels intact.
    """
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def skill_scores(profile: Profile) -> dict[str, SkillScore]:
    """
    Score known skills and hashtags using only the supplied, already-filtered profile.

    Skill declarations count once. A job tag counts once unless its name already occurs
    in that entry's text. Matching uses whole phrases, longest first, and never infers
    aliases or undisplayed endorsements. Legacy Skills entries are read from their text.

    Args:
        profile (Profile): Visible profile after configured section exclusions.

    Returns:
        dict[str, SkillScore]: Display labels and auditable scores, sorted by descending weight then name.
    """
    blocks: list[tuple[list[str], list[Skill]]] = [(profile.intro, [])]
    declarations: dict[str, Skill] = {}
    for section in profile.sections:
        for entry in section.entries:
            if section_key(section.key) == "skills":
                skills = entry.skills or ([Skill(entry.title, endorsement_count(entry.paragraphs))] if entry.title.strip() else [])
                for skill in skills:
                    key = _normalized(skill.name)
                    previous = declarations.get(key)
                    if previous is None or skill.endorsements > previous.endorsements:
                        declarations[key] = skill
                continue
            lines = [entry.title, *entry.paragraphs]
            text = _normalized(" ".join(lines))
            lines.extend(link.label for link in entry.links if link.label != link.url and _normalized(link.label) not in text)
            blocks.append((lines, entry.skills))
    blocks.extend(([skill.name], [skill]) for skill in declarations.values())
    labels: dict[str, str] = {}
    endorsements: dict[str, int] = {}
    for lines, skills in blocks:
        for skill in [*skills, *(Skill(match[1]) for line in lines for match in _HASHTAG.finditer(line))]:
            key = _normalized(skill.name)
            if key:
                labels.setdefault(key, skill.name.strip())
                endorsements[key] = max(endorsements.get(key, 0), skill.endorsements)
    if not labels:
        return {}
    alternatives = "|".join(re.escape(key) for key in sorted(labels, key=lambda key: (-len(key), key)))
    pattern = re.compile(r"(?<![\w+])(?:" + alternatives + r")(?![\w+#])")
    references: Counter[str] = Counter()
    for lines, skills in blocks:
        found = Counter(match[0] for match in pattern.finditer(_normalized(" ".join(lines))))
        for key in {_normalized(skill.name) for skill in skills}:
            if key:
                found[key] = max(found[key], 1)
        references.update(found)
    scores = {labels[key]: SkillScore(references[key], endorsements.get(key, 0)) for key in labels}
    return dict(sorted(scores.items(), key=lambda item: (-item[1].weight, _normalized(item[0]))))


def render_skill_cloud(scores: dict[str, SkillScore], directory: Path) -> str | None:
    """
    Write a deterministic PNG and score manifest beside generated LaTeX.

    Square-root scaling and a minimum visual weight keep rarely mentioned skills
    legible beside skills with large endorsement totals. The manifest keeps raw scores.

    Args:
        scores (dict[str, SkillScore]): Nonnegative counts for each displayed label.
        directory (Path): Generated TeX directory with an assets subdirectory.

    Returns:
        str | None: Relative PNG path, or None when no skills are present.

    Raises:
        ValueError: The available canvas cannot display every skill legibly.
    """
    manifest = directory / "skills.weights.json"
    for previous in (directory / "assets").glob("skills-*.png"):
        previous.unlink()
    manifest.write_text(
        json.dumps(
            {
                name: {"references": score.references, "endorsements": score.endorsements, "weight": score.weight}
                for name, score in scores.items()
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if not scores:
        return None
    maximum = max(score.weight for score in scores.values())
    frequencies = {name: 0.1 + 0.9 * sqrt(score.weight / maximum) for name, score in scores.items()}
    for attempt in range(3):
        cloud = WordCloud(
            font_path=str(files("wordcloud").joinpath("DroidSansMono.ttf")),
            width=1800,
            height=800 * (attempt + 1),
            background_color="white",
            colormap="Blues",
            max_words=len(scores),
            min_font_size=12,
            max_font_size=140,
            prefer_horizontal=1.0,
            relative_scaling=1.0,
            random_state=0,
        ).generate_from_frequencies(frequencies)
        if len(cloud.layout_) == len(scores):
            output = BytesIO()
            cloud.to_image().save(output, format="PNG")
            data = output.getvalue()
            name = "skills-" + hashlib.sha256(data).hexdigest() + ".png"
            (directory / "assets" / name).write_bytes(data)
            return f"assets/{name}"
    raise ValueError("The skill cloud could not fit every label. Set style.skills_word_cloud: false to render the complete text list.")
