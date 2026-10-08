"""
Load a strict configuration with paths anchored to its own directory.
"""

from __future__ import annotations

import hashlib
import json
import re
from importlib.resources import files
from pathlib import Path
from typing import Literal, TypedDict
from urllib.parse import urlsplit

import cattrs
import yaml
from attrs import field, frozen
from jsonschema import Draft202012Validator, FormatChecker

from resumeme.compiler.constants.backend import AST_PACKAGE, CONFIG_SCHEMA
from resumeme.compiler.constants.links import DEFAULT_PROJECT_FILTER
from resumeme.compiler.constants.lists import BODY_HEADINGS
from resumeme.compiler.constants.sections import DEFAULT_SECTION_ORDER

__all__ = [
    "Capture",
    "Codex",
    "CodexSkills",
    "CompanyTarget",
    "Config",
    "Education",
    "EducationSelector",
    "Experience",
    "GitHub",
    "GitHubContributions",
    "JobSelector",
    "LinkedIn",
    "Output",
    "Ownership",
    "Pages",
    "ProjectSelector",
    "Projects",
    "Readme",
    "Style",
    "StyleOverrides",
    "load_config",
    "project_path",
]


@frozen
class Ownership:
    """
    Configure the public signing identity maintained in LinkedIn About.

    Attributes:
        update_about (bool): Update the live profile after publishing a signed release in CI.
        repository (str | None): GitHub owner/repository; None uses Actions context or the local origin.
        releases_url (str | None): Optional HTTPS short link to that repository's releases page.
    """

    update_about: bool = False
    repository: str | None = None
    releases_url: str | None = None


@frozen
class LinkedIn:
    """
    Identify the profile owner without storing authentication material.

    Attributes:
        username (str): Owner slug from the LinkedIn profile URL.
        ownership (Ownership): Optional live About update and public release destination.
    """

    username: str
    ownership: Ownership = field(factory=Ownership)


@frozen
class GitHubContributions:
    """
    Configure an optional public contribution calendar in the resume.

    Attributes:
        enabled (bool): Fetch and display public contribution activity during rendering.
        months (int): Trailing calendar months to display, from one through twelve.
        placement (Literal["profile", "appendix"]): Below the GitHub profile link or on a separate final page.
        as_of (str | None): Inclusive ISO end date; None uses today's UTC date.
    """

    enabled: bool = False
    months: int = 1
    placement: Literal["profile", "appendix"] = "profile"
    as_of: str | None = None


@frozen
class GitHub:
    """
    Configure an optional public GitHub profile link without credentials.

    Attributes:
        username (str | None): GitHub account name, or None to omit the header link.
        contributions (GitHubContributions): Optional public activity calendar.
    """

    username: str | None = None
    contributions: GitHubContributions = field(factory=GitHubContributions)


@frozen
class Readme:
    """
    Choose whether CI publishes a personal resume landing page.

    Attributes:
        mode (Literal["auto", "project", "resume"]): Auto generates on forks, project preserves the README, resume always generates.
        introduction (str | None): Optional plain-text introduction; None uses the shared resume introduction.
        output (str): Repository-relative Markdown destination, separate from the project README when overridden.
    """

    mode: Literal["auto", "project", "resume"] = "auto"
    introduction: str | None = None
    output: str = "README.md"


@frozen
class Pages:
    """
    Publish the accepted resume as a static GitHub Pages site.

    Attributes:
        enabled (bool): Deploy after successful main-branch PDF publication.
        path (str): Directory within the Pages site, with leading and trailing slashes; / serves the root.
        custom_domain (str | None): Expected Pages hostname, or None to accept the repository's configured hostname.
    """

    enabled: bool = False
    path: str = "/"
    custom_domain: str | None = None


@frozen
class CompanyTarget:
    """
    Select one employer and job for an additional tailored resume.

    Attributes:
        username (str): Company slug from its LinkedIn company URL.
        job_url (str): HTTPS URL of the specific advertised position.
        context (str): Additional tailoring preferences for this target.
        company_context (str): Company text supplied instead of fetching LinkedIn; empty fetches the company page.
        job_context (str): Job description supplied instead of fetching its URL; empty fetches the job page.
    """

    username: str
    job_url: str
    context: str = ""
    company_context: str = ""
    job_context: str = ""

    @property
    def key(self) -> str:
        """
        Identify a stable output directory without collisions between jobs at one company.

        Returns:
            str: Company slug followed by a LinkedIn job ID or a digest of an external job URL.
        """
        parsed = urlsplit(self.job_url)
        match = re.fullmatch(r"/jobs/view/(?:[^/]*-)?(\d+)/?", parsed.path)
        linkedin = parsed.hostname == "linkedin.com" or (parsed.hostname or "").endswith(".linkedin.com")
        job = match[1] if linkedin and match else hashlib.sha256(self.job_url.encode("utf-8")).hexdigest()[:16]
        return f"{self.username.lower()}/job-{job}"


@frozen
class CodexSkills:
    """
    Select evidence-backed skill suggestions and optional LinkedIn publication on tags.

    Attributes:
        enabled (bool): Generate a skill proposal when a tag is pushed.
        publish (bool): Opt in to adding missing proposed skills to LinkedIn after release publication.
        max_skills (int): Maximum number of proposed skills per tagged release.
        context (str): Selection preferences; captured profile text remains the evidence source.
    """

    enabled: bool = False
    publish: bool = False
    max_skills: int = 20
    context: str = ""


@frozen
class Codex:
    """
    Configure optional résumé summaries without storing API credentials.

    Attributes:
        enabled (bool): Allow generated summaries to replace résumé copy.
        context (str): User-supplied background, target audience, and writing preferences.
        model (str | None): Explicit Codex model, or None for the pinned CLI's default.
        about_max_words (int): Maximum words in the generated About paragraph.
        headline_max_words (int): Maximum words in the summary beneath the portrait.
        companies (list[CompanyTarget]): Additional employer/job variants; the generic resume is always retained.
        skills (CodexSkills): Independent tag-only skill generation and optional profile publication.
    """

    enabled: bool = False
    context: str = ""
    model: str | None = None
    about_max_words: int = 100
    headline_max_words: int = 18
    companies: list[CompanyTarget] = field(factory=list)
    skills: CodexSkills = field(factory=CodexSkills)


@frozen
class Capture:
    """
    Bound page loading, pagination, preview downloads, and transient retries.

    Attributes:
        page_timeout_seconds (int): Browser and HTTP request timeout.
        max_scrolls (int): Maximum expansion iterations per page.
        max_pages_per_section (int): Maximum detail pages before capture fails.
        fetch_link_previews (bool): Whether to inspect external destinations, page titles, and project previews.
        retry_attempts (int): Total attempts for transient browser and HTTP failures.
        retry_backoff_seconds (int): Initial retry delay, doubled after every failed attempt.
        retry_max_backoff_seconds (int): Maximum exponential retry delay.
        browser (Literal["firefox", "chrome"]): Selenium browser used for capture and live About updates.
    """

    page_timeout_seconds: int = 30
    max_scrolls: int = 60
    max_pages_per_section: int = 30
    fetch_link_previews: bool = True
    retry_attempts: int = 5
    retry_backoff_seconds: int = 10
    retry_max_backoff_seconds: int = 300
    browser: Literal["firefox", "chrome"] = "firefox"


@frozen
class JobSelector:
    """
    Match jobs by exact title, employer, or both, ignoring case and extra whitespace.

    Attributes:
        title (str | None): Job title to match, or any title when omitted.
        company (str | None): Employer name to match, or any employer when omitted.
    """

    title: str | None = None
    company: str | None = None


@frozen
class Experience:
    """
    Select jobs and normalize their display text without changing captured employment history.

    Attributes:
        disable (list[JobSelector]): Exclusions applied before the date window.
        last_years (int | None): Trailing calendar-year window when since is unset; None keeps all dates.
        as_of (str | None): ISO date fixing the window's endpoint; otherwise use the current UTC date.
        subheadings (list[str]): Standalone job subsection labels, matched in full without case or a trailing colon.
        reflow_soft_breaks (bool): Join soft line breaks within job text; False retains captured line boundaries.
        since (str | None): Inclusive ISO start date, taking precedence over last_years when set.
    """

    disable: list[JobSelector] = field(factory=list)
    last_years: int | None = None
    as_of: str | None = None
    subheadings: list[str] = field(factory=lambda: list(BODY_HEADINGS))
    reflow_soft_breaks: bool = True
    since: str | None = None


@frozen
class EducationSelector:
    """
    Match education by school, qualification, field of study, or a combination.

    Attributes:
        school (str | None): Exact school name, or any school when omitted.
        degree (str | None): Degree or complete qualification row, or any degree when omitted.
        major (str | None): Field of study, or any major when omitted.
    """

    school: str | None = None
    degree: str | None = None
    major: str | None = None


@frozen
class Education:
    """
    Exclude education entries without modifying the captured academic history.

    Attributes:
        disable (list[EducationSelector]): Alternative selectors whose supplied fields must all match.
    """

    disable: list[EducationSelector] = field(factory=list)


@frozen
class ProjectSelector:
    """
    Select a displayed project by name and optional captured affiliation.

    Attributes:
        name (str): Exact displayed project name, ignoring case and repeated whitespace.
        affiliation (str | None): Captured company or organization, or any affiliation when omitted.
    """

    name: str
    affiliation: str | None = None


@frozen
class Projects:
    """
    Restrict consolidated project tiles without altering the saved profile.

    Attributes:
        include (list[ProjectSelector] | None): Alternative selectors; None allows all names, while an empty list selects none.
        exclude (list[ProjectSelector]): Matching selectors remove tiles even when include also matches; empty excludes nothing.
    """

    include: list[ProjectSelector] | None = None
    exclude: list[ProjectSelector] = field(factory=list)


@frozen
class Output:
    """
    Keep portable inputs and generated outputs beneath the configuration root.

    Attributes:
        profile (str): Snapshot JSON path.
        assets (str): Downloaded PNG directory.
        tex (str): Generated LaTeX path.
        pdf (str): Final PDF path used locally and for the CI commit.
    """

    profile: str = "data/profile.json"
    assets: str = "data/assets"
    tex: str = "tex/resume.tex"
    pdf: str = "resume.pdf"


class StyleOverrides(TypedDict, total=False):
    """
    Define the optional style fields that an inline theme may override.

    Attributes:
        paper (str): A4 or letter paper name.
        profile_column_side (Literal["left", "right"]): First-page profile placement; right lets body text continue beneath it.
        accent (str): Six-digit hexadecimal hyperlink color.
        background (str): Six-digit hexadecimal page background color.
        font_size (int): Body font size in points.
        show_header_photo (bool): Whether to display the profile cover photo.
        show_headline (bool): Whether to display the captured headline beneath the portrait.
        show_table_of_contents (bool): Whether to link visible sections beneath the LinkedIn profile link.
        highlight_job_subheadings (bool): Whether to emphasize recognized job subsection labels; False keeps their text plain.
        show_connection_count (bool): Whether to display the captured connection count below the profile link.
        show_connection_link (bool): Whether to link to the captured connections page.
        display_birthday (bool): Whether to display the birthday field in enabled contact information.
        skills_word_cloud (bool): Whether to replace the Skills list with a cloud.
        skills_allow_vertical (bool): Whether the cloud may mix vertical and horizontal labels.
        ink (str): Six-digit hexadecimal body text color.
        name_color (str): Six-digit hexadecimal profile name color.
        heading_color (str): Six-digit hexadecimal section heading color.
        entry_color (str): Six-digit hexadecimal entry heading color.
        company_font_size (int): Company name size in points, independent of body and role text.
        company_color (str): Six-digit hexadecimal company name color, including linked affiliations.
        skill_colors (tuple[str, ...]): Ordered hexadecimal stops from zero to maximum displayed skill endorsements.
    """

    paper: str
    profile_column_side: Literal["left", "right"]
    accent: str
    background: str
    font_size: int
    show_header_photo: bool
    show_headline: bool
    show_table_of_contents: bool
    highlight_job_subheadings: bool
    show_connection_count: bool
    show_connection_link: bool
    display_birthday: bool
    skills_word_cloud: bool
    skills_allow_vertical: bool
    ink: str
    name_color: str
    heading_color: str
    entry_color: str
    company_font_size: int
    company_color: str
    skill_colors: tuple[str, ...]


@frozen
class Style:
    """
    Expose the small set of print choices that do not change profile content.

    Attributes:
        paper (str): A4 or letter paper name.
        profile_column_side (Literal["left", "right"]): First-page profile placement; right lets body text continue beneath it.
        accent (str): Six-digit hexadecimal hyperlink color.
        background (str): Six-digit hexadecimal page background color.
        font_size (int): Body font size in points.
        show_header_photo (bool): Whether to display the profile's cover/background photo.
        show_headline (bool): Display the captured headline beneath the portrait; hidden by default.
        show_table_of_contents (bool): Link visible sections beneath the LinkedIn profile link in the identity column.
        highlight_job_subheadings (bool): Emphasize recognized job subsection labels; False keeps their text plain.
        show_connection_count (bool): Display the captured connection count below the profile link.
        show_connection_link (bool): Link the count or a concise Connections label to its captured destination.
        display_birthday (bool): Display the birthday field when contact information is enabled.
        skills_word_cloud (bool): Replace the Skills list with a cloud weighted by references and endorsements.
        skills_allow_vertical (bool): Allow a mix of vertical and horizontal cloud labels; False keeps all labels horizontal.
        ink (str): Six-digit hexadecimal body text color.
        name_color (str): Six-digit hexadecimal profile name color.
        heading_color (str): Six-digit hexadecimal section heading color.
        entry_color (str): Six-digit hexadecimal entry heading color.
        company_font_size (int): Company name size in points, independent of body and role text.
        company_color (str): Six-digit hexadecimal company name color, including linked affiliations.
        skill_colors (tuple[str, ...]): Ordered hexadecimal stops from zero to maximum displayed skill endorsements.
        theme (str | None): Selected key in themes; None uses the base style unchanged.
        themes (dict[str, StyleOverrides]): Inline themes containing partial style overrides.
    """

    paper: str = "letter"
    profile_column_side: Literal["left", "right"] = "left"
    accent: str = "245135"
    background: str = "FFFFFF"
    font_size: int = 10
    show_header_photo: bool = True
    show_headline: bool = False
    show_table_of_contents: bool = True
    highlight_job_subheadings: bool = True
    show_connection_count: bool = False
    show_connection_link: bool = False
    display_birthday: bool = False
    skills_word_cloud: bool = True
    skills_allow_vertical: bool = False
    ink: str = "363636"
    name_color: str = "191919"
    heading_color: str = "191919"
    entry_color: str = "363636"
    company_font_size: int = 13
    company_color: str = "191919"
    skill_colors: tuple[str, ...] = ("777777", "363636")
    theme: str | None = None
    themes: dict[str, StyleOverrides] = field(factory=dict)


@frozen
class Config:
    """
    Own validated values passed between the command line and pipeline stages.

    Attributes:
        linkedin (LinkedIn): Profile identity.
        capture (Capture): Browser and download limits.
        output (Output): Paths relative to the configuration directory.
        style (Style): Print presentation choices.
        template (str | None): Optional custom template path.
        experience (Experience): Job exclusions, date window, and description text rules.
        github (GitHub): Optional public account linked beneath the LinkedIn profile.
        codex (Codex): Optional generated résumé copy and user context.
        section_order (list[str]): Enabled section keys in display order; omitted keys stay hidden.
        project_filter (str | None): Source URL regex selecting Projects entries, or None to retain every project.
        education (Education): School, degree, and major exclusions.
        readme (Readme): Automatic personal README publication on forks.
        projects (Projects): Project names and affiliations to include or exclude alongside the source URL filter.
        pages (Pages): Optional static site publication and its location within GitHub Pages.
    """

    linkedin: LinkedIn
    capture: Capture = field(factory=Capture)
    output: Output = field(factory=Output)
    style: Style = field(factory=Style)
    template: str | None = None
    experience: Experience = field(factory=Experience)
    github: GitHub = field(factory=GitHub)
    codex: Codex = field(factory=Codex)
    section_order: list[str] = field(factory=lambda: list(DEFAULT_SECTION_ORDER))
    project_filter: str | None = DEFAULT_PROJECT_FILTER
    education: Education = field(factory=Education)
    readme: Readme = field(factory=Readme)
    projects: Projects = field(factory=Projects)
    pages: Pages = field(factory=Pages)


def project_path(root: Path, value: str) -> Path:
    """
    Resolve a repository path and reject escapes, including existing symlinks.

    Args:
        root (Path): Configuration directory.
        value (str): Relative input or output path.

    Returns:
        Path: Absolute path beneath the root.

    Raises:
        ValueError: The path is absolute, points at the root, or escapes it.
    """

    # Resolve symlinks before checking containment; lexical '..' checks alone would allow existing links to escape.
    target = (root / value).resolve()

    if Path(value).is_absolute() or target == root.resolve() or not target.is_relative_to(root.resolve()):
        raise ValueError(f"Expected a path within the configuration directory: {value}")

    return target


def load_config(path: Path) -> Config:
    """
    Safely load YAML, reject unknown fields, and validate configured paths.

    Args:
        path (Path): User-maintained configuration file.

    Returns:
        Config: Schema-validated configuration with defaults applied.

    Raises:
        jsonschema.ValidationError: A value is invalid or a field is unknown.
        ValueError: A configured date window, identity, theme, or project path is inconsistent.
    """

    # Validate raw types before cattrs can coerce them, including real calendar dates for the job window.
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    schema = json.loads(files(AST_PACKAGE).joinpath(CONFIG_SCHEMA).read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(raw)
    config = cattrs.Converter(forbid_extra_keys=True).structure(raw, Config)

    # A publish opt-in must have a corresponding proposal producer.
    if config.codex.skills.publish and not config.codex.skills.enabled:
        raise ValueError("codex.skills.publish requires codex.skills.enabled.")

    # Validated ISO dates sort chronologically; reject reversed explicit bounds before any capture or rendering work.
    if config.experience.since and config.experience.as_of and config.experience.since > config.experience.as_of:
        raise ValueError("experience.since must be on or before experience.as_of.")

    # Distinct URLs for the same LinkedIn job can differ only in tracking parameters; never let them overwrite one output.
    company_keys = [company.key for company in config.codex.companies]

    if len(company_keys) != len(set(company_keys)):
        raise ValueError("codex.companies must select distinct company/job pairs.")

    # Contribution ownership is explicit: never infer a GitHub account from the LinkedIn username or a repository owner.
    if config.github.contributions.enabled and config.github.username is None:
        raise ValueError("Set github.username before enabling github.contributions.")

    # Reject selector typos even for validation-only commands; themes are user-defined, not a hard-coded registry.
    if config.style.theme is not None and config.style.theme not in config.style.themes:
        raise ValueError(f"Unknown style.theme {config.style.theme!r}; define it under style.themes or use null.")

    # Inputs, templates, and outputs share one root but must never resolve to the same file or directory.
    paths = [config.output.profile, config.output.assets, config.output.tex, config.output.pdf, config.readme.output]
    paths.extend(f"single-origin/{key}/resume.pdf" for key in company_keys)

    if config.template:
        paths.append(config.template)

    resolved = [project_path(path.resolve().parent, value) for value in paths]

    if len(resolved) != len(set(resolved)):
        raise ValueError("Input, output, and template paths must be distinct.")

    # Generated Markdown must not replace the configuration needed by the next publication.
    if project_path(path.resolve().parent, config.readme.output) == path.resolve():
        raise ValueError("readme.output must not replace the configuration file.")

    return config
