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
from resume.latex.escaping import latex_escape, latex_linked_text, latex_url
from resume.latex.experience import filter_experience
from resume.latex.header import prepare_header
from resume.latex.media import image_role, is_header_photo
from resume.latex.projects import consolidate_projects
from resume.latex.themes import resolve_style
from resume.linkedin.links import discover_profile_links
from resume.linkedin.sections import section_key
from resume.models import Section
from resume.visualization.skills import render_skill_cloud, skill_scores

if TYPE_CHECKING:
    from pathlib import Path

    from resume.config import Config
    from resume.models import Entry, Link, Media, Profile

__all__ = ["render_profile"]


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

    # Rendering must not silently promote a diagnostic capture into an apparently complete, publishable resume.
    if profile.warnings and not allow_incomplete:
        raise ValueError("Capture is incomplete: " + "; ".join(profile.warnings))

    # Older snapshots may contain unstructured URLs; discovering them is local and preserves job ownership before filtering.
    profile = discover_profile_links(profile)

    # Resolve before filtering or drawing: themes may change visibility and page settings as well as colors.
    style = resolve_style(config.style)
    target = project_path(root, config.output.tex)
    target.parent.mkdir(parents=True, exist_ok=True)
    asset_directory = target.parent / "assets"
    asset_directory.mkdir(exist_ok=True)

    def stage(items: list[Media], links: list[Link]) -> list[Media]:
        """
        Stage only existing, validated assets with content-derived filenames.

        Args:
            items (list[Media]): References from one profile block.
            links (list[Link]): Block-owned references used to resolve image click destinations.

        Returns:
            list[Media]: References relative to the generated TeX file.
        """
        result: list[Media] = []
        destinations = {link.url: link.resolved_url or link.url for link in links}

        for item in items:
            # Missing media is an explicit incomplete-build choice; normal CI must fail instead of dropping illustrations.
            if not item.path:
                if allow_incomplete:
                    continue

                raise ValueError(f"Image was not downloaded: {item.alt or item.url}")

            source = project_path(root, item.path)

            if not source.is_file() or source.suffix.lower() != ".png":
                if allow_incomplete:
                    continue

                raise ValueError(f"Expected a captured PNG asset: {item.path}")

            # Give templates stable relative paths and reuse the same filename for identical captured bytes.
            name = hashlib.sha256(source.read_bytes()).hexdigest() + ".png"
            shutil.copyfile(source, asset_directory / name)
            result.append(evolve(item, path=f"assets/{name}", link=destinations.get(item.link, item.link)))

        return result

    # Filter before scoring or staging so hidden sections and jobs contribute neither cloud weights nor referenced assets.
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

    # Connection counts are optional header metadata, not repeated intro prose or a second profile URL.
    visible, connection_count, connection_url = prepare_header(visible, style)

    # Consolidate only retained roles and posts, so exclusions cannot leak project cards back into the document.
    visible, project_links = consolidate_projects(visible, enabled="projects" not in disabled)

    # Job tags can generate a Skills card even when LinkedIn did not provide a separate Skills section.
    scores = skill_scores(visible) if style.skills_word_cloud and "skills" not in disabled else {}
    skill_cloud = render_skill_cloud(scores, target.parent, colors=style.skill_colors, background=style.background)

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
        return evolve(
            entry,
            images=[] if cloud else stage(entry.images, entry.links),
            positions=[stage_entry(position) for position in entry.positions],
        )

    # Build a template-specific view while leaving the captured snapshot available for later re-enabling of content.
    prepared = evolve(
        visible,
        images=stage([image for image in profile.images if style.show_header_photo or not is_header_photo(image)], profile.links),
        sections=[
            evolve(
                section,
                entries=[stage_entry(entry, cloud=bool(skill_cloud and section.key == "skills")) for entry in section.entries],
            )
            for section in visible.sections
            if section.entries or (skill_cloud and section.key == "skills")
        ],
    )

    # Use delimiters that do not collide with TeX braces; missing fields fail, and explicit filters own TeX escaping.
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

    def linked_text(value: str, links: list[Link]) -> str:
        """
        Keep relocated references available to hyperlinks embedded in source prose.

        Args:
            value (str): Visible text to escape and link.
            links (list[Link]): References retained on this display block.

        Returns:
            str: Safe LaTeX with observed destinations for source and consolidated links.
        """
        return latex_linked_text(value, [*profile.links, *project_links, *links])

    environment.filters["tex"] = latex_escape
    environment.filters["tex_links"] = linked_text
    environment.filters["url"] = latex_url
    environment.tests["header_photo"] = is_header_photo
    environment.filters["image_role"] = image_role

    # Custom templates receive the same filtered view as the packaged template, so presentation cannot bypass exclusions.
    if config.template:
        template = project_path(root, config.template).read_text(encoding="utf-8")
    else:
        template = files("resume.latex").joinpath("resources/resume.tex.j2").read_text(encoding="utf-8")

    content = environment.from_string(template).render(
        profile=prepared, style=style, skill_cloud=skill_cloud, connection_count=connection_count, connection_url=connection_url
    )
    target.write_text(content, encoding="utf-8")
    return target
