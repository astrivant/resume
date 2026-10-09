"""
Record safe context for a pending LinkedIn sign-in approval.
"""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, urlsplit

from resumeme.exceptions import ConfigurationError
from resumeme.linkedin.credentials import profile_username as normalize_profile_username

__all__ = ["record_approval_context"]

_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_RUN_ID = re.compile(r"[0-9]{1,20}")
_SHA = re.compile(r"[0-9a-fA-F]{7,64}")
_HOST = re.compile(r"[A-Za-z0-9.-]+")
_BASE_PATH = re.compile(r"(?:/[A-Za-z0-9._/-]*)?")


def _clean(value: str | None, *, limit: int = 256) -> str:
    """
    Remove control characters and bound values that may be written to a workflow log.

    Args:
        value (str | None): Environment or configuration value.
        limit (int): Maximum output length.

    Returns:
        str: A single-line display value, or ``not available``.
    """
    if value is None:
        return "not available"

    normalized = " ".join("".join(character if character.isprintable() else " " for character in value).split())
    return normalized[:limit] or "not available"


def _markdown_cell(value: str) -> str:
    """
    Escape a sanitized value for a GitHub Actions Markdown table cell.

    Args:
        value (str): Single-line display value.

    Returns:
        str: Value with Markdown table delimiters escaped.
    """
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("|", "&#124;")
        .replace("`", "&#96;")
        .replace("[", "&#91;")
        .replace("]", "&#93;")
    )


def _run_url(server_url: str, repository: str, run_id: str) -> str | None:
    """
    Build a run link from validated GitHub Actions context.

    Args:
        server_url (str): Actions server origin.
        repository (str): ``OWNER/REPOSITORY`` from the runner environment.
        run_id (str): Numeric Actions run identifier.

    Returns:
        str | None: HTTPS Actions run URL, or None when the values are not valid.
    """
    if not _REPOSITORY.fullmatch(repository) or not _RUN_ID.fullmatch(run_id):
        return None

    try:
        origin = urlsplit(server_url)
        port = origin.port
    except ValueError:
        return None

    if (
        origin.scheme != "https"
        or not origin.hostname
        or not _HOST.fullmatch(origin.hostname)
        or origin.username is not None
        or origin.password is not None
    ):
        return None

    if origin.query or origin.fragment or not _BASE_PATH.fullmatch(origin.path):
        return None

    authority = origin.hostname

    if port is not None:
        authority = f"{authority}:{port}"

    prefix = origin.path.rstrip("/")
    repo_path = "/".join(quote(part, safe="") for part in repository.split("/"))
    return f"https://{authority}{prefix}/{repo_path}/actions/runs/{run_id}"


def _summary_path() -> Path | None:
    """
    Return the Actions-provided summary destination when running in a workflow.

    Returns:
        Path | None: Existing environment-provided destination, or None for local runs.
    """
    value = os.environ.get("GITHUB_STEP_SUMMARY")
    return Path(value) if value else None


def record_approval_context(*, profile_username: str | None, browser: str, checkpoint: str, timeout_seconds: int) -> None:
    """
    Print and retain non-secret run context for a LinkedIn app approval request.

    Args:
        profile_username (str | None): Public configured LinkedIn profile identifier.
        browser (str): Selected browser name.
        checkpoint (str): Safe challenge category, not page text.
        timeout_seconds (int): Maximum time to wait for the current approval.

    Returns:
        None: Context is printed and appended to the Actions step summary when available.
    """
    try:
        profile = normalize_profile_username(profile_username or "")
    except ConfigurationError:
        profile = "not available"

    repository = _clean(os.environ.get("GITHUB_REPOSITORY"))
    workflow = _clean(os.environ.get("GITHUB_WORKFLOW"))
    job_id = _clean(os.environ.get("GITHUB_JOB"))
    event = _clean(os.environ.get("GITHUB_EVENT_NAME"))
    reference = _clean(os.environ.get("GITHUB_REF"))
    commit = os.environ.get("GITHUB_SHA", "")
    commit = commit[:12] if _SHA.fullmatch(commit) else "not available"
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "")
    run_url = _run_url(os.environ.get("GITHUB_SERVER_URL", "https://github.com"), repository, run_id)
    started = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    fields = [
        ("Requested at (UTC)", started),
        ("LinkedIn profile", profile),
        ("Browser", _clean(browser)),
        ("Workflow", workflow),
        ("Job ID", job_id),
        ("Trigger", event),
        ("Ref", reference),
        ("Commit", commit),
        ("Run", f"{run_id or 'not available'} (attempt {attempt or 'not available'})"),
        ("Checkpoint", _clean(checkpoint)),
        ("Approval wait (seconds)", str(timeout_seconds)),
    ]

    if run_url:
        fields.append(("Actions run", run_url))

    # Print before polling so the context is visible while the user is checking their phone.
    print("\nLinkedIn sign-in audit context", flush=True)
    print("Approve only if you initiated this run and its details match.", flush=True)

    for name, value in fields:
        print(f"  {name}: {value}", flush=True)

    print("No login credentials, cookies, checkpoint text, or browser-session details are recorded here.\n", flush=True)

    summary_path = _summary_path()

    if summary_path is None:
        return

    lines = [
        "### LinkedIn sign-in approval audit",
        "",
        "Approve the notification only if you initiated this run and these details match.",
        "",
    ]

    for name, value in fields:
        safe_name = _markdown_cell(_clean(name))
        safe_value = _markdown_cell(_clean(value))

        if name == "Actions run" and run_url:
            safe_value = f"[Open workflow run]({run_url})"

        lines.append(f"| {safe_name} | {safe_value} |")

        if name == "Requested at (UTC)":
            lines.insert(-1, "| Field | Value |")
            lines.insert(-1, "| --- | --- |")

    lines.extend(["", "No login credentials, cookies, checkpoint text, or browser-session details are recorded in this summary.", ""])

    try:
        with summary_path.open("a", encoding="utf-8") as summary:
            summary.write("\n".join(lines))
    except OSError:
        # The sign-in flow remains usable if the optional summary file is unavailable.
        print("Could not append the LinkedIn approval context to the Actions step summary; see this job's output.", flush=True)
