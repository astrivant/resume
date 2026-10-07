"""
Translate validated profile values into safe, deterministic LaTeX source.
"""

from __future__ import annotations

import hashlib
import shutil
from importlib.resources import files
from typing import TYPE_CHECKING

from attrs import evolve
from jinja2 import Environment, StrictUndefined

from resume.config import project_path
from resume.latex.escaping import latex_escape, latex_url
from resume.latex.experience import filter_experience
from resume.linkedin.sections import section_key
from resume.models import Section
from resume.visualization.skills import render_skill_cloud, skill_scores

if TYPE_CHECKING:
    from pathlib import Path

    from resume.config import Config
    from resume.models import Entry, Media, Profile

__all__ = ["render_profile"]


def _is_header_photo(image: Media) -> bool:
    """
    Identify a LinkedIn cover photo for visibility filtering and banner sizing.

    Args:
        image (Media): Captured image with its accessible label and source URL.

    Returns:
        bool: Whether the label or LinkedIn image URL identifies a cover/background photo.
    """
    label = image.alt.casefold()
    return "background" in label or "cover" in label or "profile-displaybackgroundimage" in image.url.casefold()


def render_profile(profile: Profile, config: Config, root: Path, *, allow_incomplete: bool = False) -> Path:
    """
    Render enabled sections and stage their referenced images alongside the TeX source.

    Args:
        profile (Profile): Validated snapshot.
        config (Config): Section exclusions, template, style, and output settings.
        root (Path): Configuration directory.
        allow_incomplete (bool): Explicitly accept capture warnings or missing assets.

    Returns:
        Path: Generated LaTeX source.

    Raises:
        ValueError: Capture warnings or missing assets prevent a complete résumé.
    """
    if profile.warnings and not allow_incomplete:
        raise ValueError("Capture is incomplete: " + "; ".join(profile.warnings))
    target = project_path(root, config.output.tex)
    target.parent.mkdir(parents=True, exist_ok=True)
    asset_directory = target.parent / "assets"
    asset_directory.mkdir(exist_ok=True)

    def stage(items: list[Media]) -> list[Media]:
        """
        Stage only existing, validated assets with content-derived filenames.

        Args:
            items (list[Media]): References from one profile block.

        Returns:
            list[Media]: References relative to the generated TeX file.
        """
        result: list[Media] = []
        for item in items:
            if not item.path:
                if allow_incomplete:
                    continue
                raise ValueError(f"Image was not downloaded: {item.alt or item.url}")
            source = project_path(root, item.path)
            if not source.is_file() or source.suffix.lower() != ".png":
                if allow_incomplete:
                    continue
                raise ValueError(f"Expected a captured PNG asset: {item.path}")
            name = hashlib.sha256(source.read_bytes()).hexdigest() + ".png"
            shutil.copyfile(source, asset_directory / name)
            result.append(evolve(item, path=f"assets/{name}"))
        return result

    disabled = {section_key(key) for key in config.disable}
    visible = evolve(
        profile,
        sections=[
            evolve(
                section,
                key=section_key(section.key),
                entries=filter_experience(section.entries, config.experience)
                if section_key(section.key) == "experience"
                else section.entries,
            )
            for section in profile.sections
            if section_key(section.key) not in disabled
        ],
    )
    scores = skill_scores(visible) if config.style.skills_word_cloud and "skills" not in disabled else {}
    skill_cloud = render_skill_cloud(scores, target.parent)
    if skill_cloud and not any(section.key == "skills" for section in visible.sections):
        visible = evolve(visible, sections=[*visible.sections, Section("skills", "Skills")])

    def stage_entry(entry: Entry, *, cloud: bool = False) -> Entry:
        """
        Give custom templates staged paths for retained grouped roles as well as their parent.

        Args:
            entry (Entry): Visible entry after job filtering.
            cloud (bool): Whether the generated cloud replaces this entry's illustrations.

        Returns:
            Entry: Visible content with image paths relative to the generated TeX.
        """
        return evolve(entry, images=[] if cloud else stage(entry.images), positions=[stage_entry(position) for position in entry.positions])

    prepared = evolve(
        visible,
        images=stage([image for image in profile.images if config.style.show_header_photo or not _is_header_photo(image)]),
        sections=[
            evolve(
                section,
                entries=[stage_entry(entry, cloud=bool(skill_cloud and section.key == "skills")) for entry in section.entries],
            )
            for section in visible.sections
            if section.entries or (skill_cloud and section.key == "skills")
        ],
    )
    environment = Environment(
        undefined=StrictUndefined,
        autoescape=False,
        block_start_string="((*",
        block_end_string="*))",
        variable_start_string="(((",
        variable_end_string=")))",
        comment_start_string="((#",
        comment_end_string="#))",
        keep_trailing_newline=True,
    )
    environment.filters["tex"] = latex_escape
    environment.filters["url"] = latex_url
    environment.tests["header_photo"] = _is_header_photo
    if config.template:
        template = project_path(root, config.template).read_text(encoding="utf-8")
    else:
        template = files("resume.latex").joinpath("resources/resume.tex.j2").read_text(encoding="utf-8")
    content = environment.from_string(template).render(profile=prepared, style=config.style, skill_cloud=skill_cloud)
    target.write_text(content, encoding="utf-8")
    return target
