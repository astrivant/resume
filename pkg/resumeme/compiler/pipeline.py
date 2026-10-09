"""
Translate validated profile values into safe, deterministic LaTeX source.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from datetime import UTC, datetime
from functools import partial
from importlib.resources import files
from typing import TYPE_CHECKING

from attrs import evolve
from jinja2 import Environment, StrictUndefined

from resumeme.compiler.asts.contributions import calendar_window, save_calendar, validate_calendar
from resumeme.compiler.asts.links import discover_profile_links
from resumeme.compiler.asts.profile import Section
from resumeme.compiler.asts.sections import section_key
from resumeme.compiler.asts.summary import load_summary
from resumeme.compiler.backends.latex.assets import stage_website_icon
from resumeme.compiler.backends.latex.escaping import latex_contact_text, latex_escape, latex_linked_text, latex_url
from resumeme.compiler.backends.latex.formatting import format_tex_source
from resumeme.compiler.constants.backend import (
    BLOCK_END,
    BLOCK_START,
    COMMENT_END,
    COMMENT_START,
    LATEX_PACKAGE,
    TEMPLATE,
    VARIABLE_END,
    VARIABLE_START,
)
from resumeme.compiler.constants.contributions import CONTRIBUTION_COLORS
from resumeme.compiler.passes.contact import contact_email_url, is_contact_website, prepare_contact
from resumeme.compiler.passes.context import resolve_dates
from resumeme.compiler.passes.header import is_pronouns, prepare_header, prepare_header_logos, prepare_header_position
from resumeme.compiler.passes.headings import distinct_heading, is_body_heading
from resumeme.compiler.passes.lists import text_blocks
from resumeme.compiler.passes.locations import job_locations
from resumeme.compiler.passes.media import employer_badge, employer_name_index, image_role, is_header_photo, school_badge
from resumeme.compiler.passes.navigation import experience_navigation
from resumeme.compiler.passes.ordering import order_sections
from resumeme.compiler.passes.ownership import without_ownership_metadata
from resumeme.compiler.passes.privacy import without_profile_location
from resumeme.compiler.passes.progression import experience_layout
from resumeme.compiler.passes.project_layout import company_logos, project_layout
from resumeme.compiler.passes.projects import consolidate_projects
from resumeme.compiler.passes.skills import expand_skill_summaries, without_project_skill_rows
from resumeme.compiler.passes.summary import apply_summary, summary_digest
from resumeme.compiler.passes.themes import resolve_style
from resumeme.compiler.passes.visibility import visible_profile
from resumeme.config import project_path
from resumeme.exceptions import ProfileError
from resumeme.visualization.skills import render_skill_cloud, skill_scores

if TYPE_CHECKING:
    from datetime import date
    from pathlib import Path

    from resumeme.compiler.asts.contributions import ContributionCalendar
    from resumeme.compiler.asts.profile import Entry, Link, Media, Profile
    from resumeme.compiler.asts.summary import CompanyEvidence
    from resumeme.config import Config

__all__ = ["render_profile"]
_LOGGER = logging.getLogger(__name__)


def render_profile(
    profile: Profile,
    config: Config,
    root: Path,
    *,
    allow_incomplete: bool = False,
    summary_path: Path | None = None,
    contributions: ContributionCalendar | None = None,
    company: CompanyEvidence | None = None,
    today: date | None = None,
) -> Path:
    """
    Render enabled sections and stage their referenced images alongside the TeX source.

    Args:
        profile (Profile): Validated snapshot.
        config (Config): Section exclusions, template, style, and output settings.
        root (Path): Configuration directory.
        allow_incomplete (bool): Explicitly accept capture warnings or missing assets.
        summary_path (Path | None): Explicit generated-copy artifact, validated against this capture and configuration.
        contributions (ContributionCalendar | None): Acquired public activity for the optional GitHub graph; never fetched by this function.
        company (CompanyEvidence | None): Employer evidence bound to a tailored summary; None selects generic copy.
        today (date | None): UTC reference date for replay; orchestration reads the clock once when omitted.

    Returns:
        Path: Generated LaTeX source.

    Raises:
        ProfileError: Capture warnings or missing assets prevent a complete résumé.
    """

    # Rendering must not silently promote a diagnostic capture into an apparently complete, publishable resume.
    if profile.warnings and not allow_incomplete:
        raise ProfileError("Capture is incomplete: " + "; ".join(profile.warnings))

    # Resolve external time once at the boundary; pure passes and summary validation receive identical fixed endpoints.
    config = resolve_dates(config, today=today or datetime.now(UTC).date())
    _LOGGER.info("Rendering LaTeX", extra={"profile.sections": len(profile.sections), "summary.enabled": summary_path is not None})
    # Validate against the original inputs before display passes remove or relocate source text.
    summary = (
        load_summary(summary_path, username=profile.username, source_digest=summary_digest(profile, config, company), settings=config.codex)
        if summary_path is not None
        else None
    )

    # Older snapshots may contain unstructured URLs; discovering them is local and preserves job ownership before filtering.
    profile = discover_profile_links(profile)

    # Resolve before filtering or drawing: themes may change visibility and page settings as well as colors.
    style = resolve_style(config.style)
    target = project_path(root, config.output.tex)
    target.parent.mkdir(parents=True, exist_ok=True)

    # Validate external activity before publishing generated source, and retain the exact observations beside that source.
    if config.github.contributions.enabled:
        if contributions is None or config.github.username is None:
            raise ProfileError("Enabled GitHub contributions require a captured calendar and github.username.")

        validate_calendar(contributions, config.github.username, *calendar_window(config.github.contributions))
        save_calendar(contributions, target.parent / "github-contributions.json")
    elif contributions is not None:
        raise ProfileError("Enable github.contributions before supplying a calendar.")

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

                raise ProfileError(f"Image was not downloaded: {item.alt or item.url}")

            source = project_path(root, item.path)

            if not source.is_file() or source.suffix.lower() != ".png":
                if allow_incomplete:
                    continue

                raise ProfileError(f"Expected a captured PNG asset: {item.path}")

            # Give templates stable relative paths and reuse the same filename for identical captured bytes.
            name = hashlib.sha256(source.read_bytes()).hexdigest() + ".png"
            shutil.copyfile(source, asset_directory / name)
            result.append(evolve(item, path=f"assets/{name}", link=destinations.get(item.link, item.link)))

        return result

    # Filter before scoring or staging so hidden sections and jobs contribute neither cloud weights nor referenced assets.
    enabled = {section_key(key) for key in config.section_order}
    visible = visible_profile(profile, config)

    # Apply the same privacy opt-out used before capture artifacts are published.
    if not style.display_location:
        visible = without_profile_location(visible)

    # Signing identity belongs on LinkedIn's About, while the PDF keeps only the person's authored profile content.
    visible = without_ownership_metadata(visible)

    # Connection counts are optional header metadata, not repeated intro prose or a second profile URL.
    summary_headline = " ".join(summary.headline.split()) if summary and style.show_headline else ""
    visible, connection_count, connection_url = prepare_header(visible, evolve(style, show_headline=False) if summary_headline else style)
    visible, current_position = prepare_header_position(visible, captured=profile, display=style.display_current_position)

    # An explicit unfiltered header opt-in stages only the selected company logo, never the excluded role's projects or attachments.
    if current_position and current_position.logo:
        staged = stage([current_position.logo], [])
        current_position = evolve(current_position, logo=staged[0] if staged else None)

    if summary:
        visible = apply_summary(visible, summary, about_enabled="about" in enabled)

    # Normalize contact labels, links, and privacy before scoring or staging, including the view supplied to custom templates.
    visible = evolve(
        visible,
        sections=[
            evolve(
                section,
                title="Contact",
                entries=prepare_contact(
                    section.entries,
                    display_birthday=style.display_birthday,
                    display_websites=style.display_websites,
                    display_phone=style.display_phone,
                ),
            )
            if section.key == "contact"
            else section
            for section in visible.sections
        ],
    )

    # Resolve branding only for retained Website fields, so hidden contacts need neither icon files nor network access.
    website_icon = None

    if style.website_icon and any(
        is_contact_website(entry) for section in visible.sections if section.key == "contact" for entry in section.entries
    ):
        website_icon = stage_website_icon(style.website_icon, config, root, asset_directory)

    # Consolidate only retained roles and posts, so exclusions cannot leak project cards back into the document.
    visible, project_links = consolidate_projects(
        visible,
        enabled="projects" in enabled,
        project_filter=config.project_filter,
        include=config.projects.include,
        exclude=config.projects.exclude,
    )

    # LinkedIn's collapsed counts refer to captured tags or reverse Skills associations, not printable skill names.
    visible = expand_skill_summaries(visible)

    # Job tags can generate a Skills card even when LinkedIn did not provide a separate Skills section.
    scores = skill_scores(visible) if style.skills_word_cloud and "skills" in enabled else {}
    skill_cloud = render_skill_cloud(
        scores, target.parent, colors=style.skill_colors, background=style.background, allow_vertical=style.skills_allow_vertical
    )

    if skill_cloud and not any(section.key == "skills" for section in visible.sections):
        visible = evolve(visible, sections=[*visible.sections, Section("skills", "Skills")])

    # Project tags belong exclusively in Skills; remove their display rows after scoring, including for custom templates.
    visible = without_project_skill_rows(visible, source=profile)

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

    # Filter identity photos before staging so hidden portraits need no asset and consume no layout space in either column.
    # Keep the captured snapshot available for later re-enabling of content, including through custom templates.
    prepared = evolve(
        visible,
        images=stage(
            [
                image
                for image in visible.images
                if (style.show_header_photo or not is_header_photo(image))
                and (style.display_profile_photo or image_role(image, header=True) != "portrait")
            ],
            profile.links,
        ),
        sections=[
            evolve(
                section,
                entries=[stage_entry(entry, cloud=bool(skill_cloud and section.key == "skills")) for entry in section.entries],
            )
            for section in visible.sections
            if section.entries or section.key == "contact" or (skill_cloud and section.key == "skills")
        ],
    )

    # Apply order after generated sections and empty-section removal; custom templates receive the same sequence as navigation.
    prepared = evolve(prepared, sections=order_sections(prepared.sections, config.section_order))

    # Use delimiters that do not collide with TeX braces; missing fields fail, and explicit filters own TeX escaping.
    environment = Environment(
        undefined=StrictUndefined,
        autoescape=False,
        block_start_string=BLOCK_START,
        block_end_string=BLOCK_END,
        variable_start_string=VARIABLE_START,
        variable_end_string=VARIABLE_END,
        comment_start_string=COMMENT_START,
        comment_end_string=COMMENT_END,
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
    environment.filters["tex_contact"] = latex_contact_text
    environment.filters["contact_email_url"] = contact_email_url
    environment.filters["url"] = latex_url
    environment.tests["header_photo"] = is_header_photo
    environment.tests["pronouns"] = is_pronouns
    environment.tests["contact_website"] = is_contact_website
    environment.filters["image_role"] = image_role
    environment.filters["employer_badge"] = employer_badge
    environment.filters["employer_name_index"] = employer_name_index
    environment.filters["school_badge"] = school_badge
    environment.filters["text_blocks"] = text_blocks
    environment.filters["job_text_blocks"] = partial(
        text_blocks, reflow_soft_breaks=config.experience.reflow_soft_breaks, subheadings=config.experience.subheadings
    )
    environment.filters["distinct_heading"] = distinct_heading
    environment.filters["body_heading"] = partial(is_body_heading, labels=config.experience.subheadings)
    environment.filters["experience_layout"] = experience_layout
    environment.filters["job_locations"] = job_locations
    companies = company_logos(prepared)
    environment.filters["project_layout"] = partial(project_layout, companies=companies)

    environment.filters["header_logos"] = partial(prepare_header_logos, companies=companies)

    # Custom templates receive the same filtered view as the packaged template, so presentation cannot bypass exclusions.
    if config.template:
        template = project_path(root, config.template).read_text(encoding="utf-8")
    else:
        template = files(LATEX_PACKAGE).joinpath(TEMPLATE).read_text(encoding="utf-8")

    # Share display order between section rendering and navigation, after exclusions and generated sections have settled.
    # Numeric destinations avoid collisions or TeX injection from duplicate, unfamiliar, or punctuation-heavy section keys.
    section_navigation = [(f"resumeme-section-{index}", section) for index, section in enumerate(prepared.sections)]
    _LOGGER.debug(
        "Presentation passes completed",
        extra={
            "profile.sections": [section.key for section in prepared.sections],
            "profile.entries": sum(len(section.entries) for section in prepared.sections),
        },
    )
    jobs = experience_navigation(section_navigation)
    environment.filters["job_destination"] = jobs.destination
    environment.filters["job_association"] = jobs.association
    content = environment.from_string(template).render(
        profile=prepared,
        style=style,
        skill_cloud=skill_cloud,
        summary_headline=summary_headline,
        connection_count=connection_count,
        connection_url=connection_url,
        github_username=config.github.username,
        contributions=contributions,
        contribution_colors=CONTRIBUTION_COLORS,
        contribution_placement=config.github.contributions.placement,
        contact_enabled="contact" in enabled,
        website_icon=website_icon,
        current_position=current_position,
        section_navigation=section_navigation,
    )
    # Normalize Jinja's loop whitespace for readable, reviewable generated source.
    target.write_text(format_tex_source(content), encoding="utf-8")
    _LOGGER.info("LaTeX rendered", extra={"file.path": str(target), "file.size": target.stat().st_size})
    return target
