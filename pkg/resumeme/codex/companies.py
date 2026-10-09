"""
Acquire employer context and compile additional resumes from explicitly selected summary artifacts.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import requests
from attrs import asdict
from bs4 import BeautifulSoup

from resumeme.codex.request import prepare_summary
from resumeme.compiler.asts.contributions import calendar_window, validate_calendar
from resumeme.compiler.asts.summary import CompanyEvidence, load_summary
from resumeme.compiler.backends.latex.compilation import compile_pdf
from resumeme.compiler.passes.context import resolve_dates
from resumeme.compiler.passes.summary import summary_digest
from resumeme.compiler.pipeline import render_profile
from resumeme.config import company_config, project_path
from resumeme.exceptions import SummaryError
from resumeme.github.contributions import fetch_calendar
from resumeme.linkedin.media import fetch_public
from resumeme.linkedin.retrying import retry

if TYPE_CHECKING:
    from pathlib import Path

    from resumeme.compiler.asts.contributions import ContributionCalendar
    from resumeme.compiler.asts.profile import Profile
    from resumeme.config import CompanyTarget, Config

__all__ = ["company_config", "load_company", "prepare_companies", "render_companies"]

_MAX_CONTEXT = 40000


def _page_text(content: bytes, *, job: bool) -> str:
    """
    Extract company background or job requirements without treating page controls as useful evidence.

    Args:
        content (bytes): Public HTML fetched with bounded requests.
        job (bool): Select JobPosting descriptions instead of company About content.

    Returns:
        str: Plain text with the page heading and a substantive description.

    Raises:
        SummaryError: No usable description is exposed by the page.
    """
    soup = BeautifulSoup(content, "html.parser")
    kind = "JobPosting" if job else "Organization"
    descriptions: list[str] = []

    # Structured descriptions avoid navigation, cookie banners, and recommendation cards on job boards.
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            raw: object = json.loads(script.get_text())
        except json.JSONDecodeError:
            continue

        queue: list[object] = [raw]

        while queue:
            value = queue.pop()

            if isinstance(value, list):
                queue.extend(value)
            elif isinstance(value, dict):
                queue.extend(value.values())
                types = value.get("@type")

                if (types == kind or isinstance(types, list) and kind in types) and isinstance(value.get("description"), str):
                    label = value.get("title" if job else "name")

                    if isinstance(label, str) and label.strip():
                        descriptions.append(label)

                    descriptions.append(value["description"])

    # LinkedIn's public company and job pages expose descriptions in different expandable content blocks.
    if not descriptions:
        selectors = (
            ".show-more-less-html__markup, #job-details, [data-test-id='job-description']"
            if job
            else "[data-test-id='about-us__description'], .about-us__description, .org-about-us-organization-description__text"
        )
        descriptions = [str(node) for node in soup.select(selectors)]

    if not descriptions:
        raise SummaryError("The page exposes no company/job description. Supply company_context or job_context in codex.companies.")

    heading = soup.find("h1")
    parts = [heading.get_text(" ", strip=True)] if heading else []

    for description in descriptions:
        fragment = BeautifulSoup(description, "html.parser")

        for hidden in fragment.select("script, style, nav, footer, form, [hidden], [aria-hidden='true']"):
            hidden.decompose()

        text = " ".join(fragment.get_text(" ", strip=True).split())

        if text and text not in parts:
            parts.append(text)

    result = "\n\n".join(parts)

    if len(result) < 40 or len(result) > _MAX_CONTEXT:
        raise SummaryError("Company/job evidence must contain 40-40000 characters. Supply a complete text override in the config.")

    return result


def _fetch_context(url: str, config: Config, *, job: bool) -> str:
    """
    Retrieve public context with the project's bounded requests and exponential retry policy.

    Args:
        url (str): Public company or specific job URL.
        config (Config): Request timeouts and retry settings.
        job (bool): Select the job-description parser.

    Returns:
        str: Acquired plain-text company or job evidence.

    Raises:
        SummaryError: A login wall, unavailable listing, or unsupported page requires a configured text override.
        requests.RequestException: Transient failures exhaust the configured retries.
    """
    with requests.Session() as session:
        session.trust_env = False

        def acquire() -> str:
            """
            Fetch and parse one complete page without forwarding account credentials.

            Returns:
                str: Public page evidence suitable for a summary prompt.
            """
            try:
                content, destination = fetch_public(session, url, config.capture.page_timeout_seconds)
            except requests.HTTPError as error:
                if error.response is not None and error.response.status_code not in {408, 429, 500, 502, 503, 504}:
                    raise SummaryError(f"Cannot read {url}; supply company_context or job_context for this target.") from error

                raise

            if any(part in urlsplit(destination).path.lower() for part in ("authwall", "checkpoint", "/login", "/signin")):
                raise SummaryError(f"{url} requires login. Supply company_context or job_context for this target.")

            return _page_text(content, job=job)

        return retry(
            acquire,
            attempts=config.capture.retry_attempts,
            backoff=config.capture.retry_backoff_seconds,
            max_backoff=config.capture.retry_max_backoff_seconds,
            exceptions=(requests.RequestException, OSError),
        )


def prepare_companies(profile: Profile, config: Config, root: Path) -> list[Path]:
    """
    Prepare independent employer requests after acquiring or accepting explicit source text.

    Args:
        profile (Profile): Validated applicant capture.
        config (Config): Enabled Codex settings and company/job targets.
        root (Path): Configuration directory containing the request cache.

    Returns:
        list[Path]: Per-target directories containing prompt, schema, and exact employer evidence.

    Raises:
        SummaryError: Generation is disabled, capture is incomplete, or employer evidence cannot be acquired.
    """
    if not config.codex.enabled or profile.warnings:
        raise SummaryError("Company summaries require codex.enabled and a complete profile capture.")

    directories: list[Path] = []
    logging.getLogger(__name__).info("Preparing tailored summaries", extra={"summary.companies": len(config.codex.companies)})
    companies: dict[str, str] = {}

    for target in config.codex.companies:
        settings = company_config(config, target, root=root)
        company_url = f"https://www.linkedin.com/company/{target.username}/about/"

        # Multiple jobs at one employer share a fetch, but each explicit company override remains independent.
        if not target.company_context and company_url not in companies:
            companies[company_url] = _fetch_context(company_url, settings, job=False)

        company = target.company_context or companies[company_url]
        job = target.job_context or _fetch_context(target.job_url, settings, job=True)

        if any(not text.strip() or len(text) > _MAX_CONTEXT for text in (company, job)):
            raise SummaryError("Company and job context must be nonempty and at most 40000 characters each.")

        directories.append(prepare_summary(profile, settings, root, CompanyEvidence(target, company, job)))

    return directories


def load_company(path: Path, target: CompanyTarget) -> CompanyEvidence:
    """
    Reuse the exact employer evidence without contacting a page that may have changed since generation.

    Args:
        path (Path): Explicit company.json artifact from request preparation.
        target (CompanyTarget): Current configured target, including text overrides and writing preferences.

    Returns:
        CompanyEvidence: Validated target-bound source text.

    Raises:
        SummaryError: The artifact is malformed, belongs to another target, or no longer matches its configuration.
    """
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    recorded = raw.get("target") if isinstance(raw, dict) else None

    # Bundles created before partial configs omitted this field; absent overrides still mean an unchanged inherited config.
    if isinstance(recorded, dict):
        recorded = {"overrides": {}, **recorded}

    if not isinstance(raw, dict) or set(raw) != {"target", "company", "job"} or recorded != asdict(target):
        raise SummaryError("Company summary target changed. Prepare and generate this company's summary again.")

    company, job = raw["company"], raw["job"]

    if (
        not isinstance(company, str)
        or not isinstance(job, str)
        or any(not text.strip() or len(text) > _MAX_CONTEXT for text in (company, job))
    ):
        raise SummaryError("Company summary evidence must include bounded, nonempty company and job descriptions.")

    return CompanyEvidence(target, company, job)


def render_companies(
    profile: Profile,
    config: Config,
    root: Path,
    summaries: Path,
    *,
    compile_documents: bool,
    contributions: ContributionCalendar | None = None,
) -> list[Path]:
    """
    Validate every selected response before rendering the independent employer variants.

    Args:
        profile (Profile): Original applicant capture, never mutated by tailoring.
        config (Config): Company list and shared presentation settings.
        root (Path): Configuration directory.
        summaries (Path): Explicit directory containing company/job artifact folders.
        compile_documents (bool): Compile PDFs when True, otherwise produce TeX for review.
        contributions (ContributionCalendar | None): Generic calendar reused for matching target accounts/windows; others are fetched once.

    Returns:
        list[Path]: Configured company's PDFs or TeX sources in configuration order.

    Raises:
        SummaryError: A required summary is stale, malformed, or belongs to another company or applicant.
    """
    today = datetime.now(UTC).date()
    selected: list[tuple[CompanyEvidence, Path, Config]] = []

    # Missing or invalid variants must fail before any existing target PDF is replaced.
    for target in config.codex.companies:
        directory = project_path(summaries, target.key)
        company = load_company(directory / "company.json", target)
        response = directory / "summary.json"
        settings = resolve_dates(company_config(config, target, root=root), today=today)
        load_summary(response, username=profile.username, source_digest=summary_digest(profile, settings, company), settings=settings.codex)
        selected.append((company, response, settings))

    results: list[Path] = []
    calendars = {(contributions.username, contributions.start, contributions.end): contributions} if contributions else {}

    for company, response, settings in selected:
        calendar = None

        # Reuse exact observations across targets; disabling the graph must not pass a calendar to the offline renderer.
        if settings.github.contributions.enabled and settings.github.username:
            start, end = calendar_window(settings.github.contributions)
            key = (settings.github.username, start.isoformat(), end.isoformat())

            if key not in calendars:
                calendars[key] = fetch_calendar(settings)

            calendar = calendars[key]
            validate_calendar(calendar, settings.github.username, start, end)

        source = render_profile(profile, settings, root, summary_path=response, contributions=calendar, company=company)
        results.append(compile_pdf(source, settings, root) if compile_documents else source)

    return results
