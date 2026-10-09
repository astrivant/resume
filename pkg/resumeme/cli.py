"""
Provide explicit configuration linting, capture, validation, rendering, and PDF build commands.
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from jsonschema import ValidationError
from selenium.common.exceptions import NoSuchWindowException, TimeoutException, WebDriverException

from resumeme.codex.companies import prepare_companies, render_companies
from resumeme.codex.request import prepare_summary
from resumeme.codex.skills import prepare_skills
from resumeme.compiler.asts.contributions import load_calendar
from resumeme.compiler.asts.profile import load_profile, save_profile
from resumeme.compiler.backends.latex.compilation import compile_pdf
from resumeme.compiler.pipeline import render_profile
from resumeme.config import Ownership, load_config, project_path
from resumeme.exceptions import ConfigurationError, ProfileError, ResumemeError
from resumeme.github.contributions import fetch_calendar
from resumeme.github.pages import build_site
from resumeme.linkedin.browser import capture_profile
from resumeme.linkedin.identity import release_destination
from resumeme.linkedin.media import cache_media
from resumeme.linkedin.ownership import publish_ownership
from resumeme.linkedin.resume import publish_resume
from resumeme.linkedin.skills import publish_skills
from resumeme.telemetry import LOG_LEVELS, logging_context, set_log_level

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["main"]
_LOGGER = logging.getLogger(__name__)


def main(argv: Sequence[str] | None = None) -> int:
    """
    Run one pipeline stage and report actionable errors without credential output.

    Args:
        argv (Sequence[str] | None): Arguments, defaulting to the process command line.

    Returns:
        int: Zero on success, two on invalid input or a failed stage.
    """

    # Keep capture separate from offline commands so CI can build committed inputs without a browser session.
    parser = argparse.ArgumentParser(description="Capture your LinkedIn profile and build an illustrated PDF résumé.")
    parser.add_argument(
        "--config", type=Path, default=Path("resumeme.config.yaml"), help="Configuration file (default: resumeme.config.yaml)"
    )
    parser.add_argument(
        "--log-level", type=str.upper, choices=LOG_LEVELS, help="Override RESUMEME_LOG_LEVEL and logging.level (default: ERROR)"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("capture", "Open the configured browser, wait for login, and save your expanded profile and images"),
        ("enrich", "Discover text links, resolve destinations, and cache previews from the saved profile"),
        ("validate", "Validate configuration and snapshot ownership"),
        ("summary-prompt", "Prepare a Codex summary prompt and output schema from visible profile text"),
        ("render", "Generate tex/resume.tex from the saved profile"),
        ("build", "Render LaTeX and compile resume.pdf with Docker or the bundled container toolchain"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument(
            "--allow-incomplete", action="store_true", help="Explicitly accept recorded capture warnings or missing images"
        )

        if name == "capture":
            command.add_argument("--connect-port", type=int, help="Attach to an explicitly opened local Firefox Marionette port")
            command.add_argument("--headless", action="store_true", help="Capture unattended using LinkedIn login environment variables")

        if name in {"render", "build"}:
            command.add_argument("--summary", type=Path, help="Generated summary JSON relative to the configuration directory")
            command.add_argument(
                "--company-summaries", type=Path, help="Explicit directory of company/job summary artifacts to render additionally"
            )
            command.add_argument(
                "--github-calendar",
                type=Path,
                help="Reuse captured calendar JSON instead of fetching GitHub; match github.contributions.as_of",
            )

        if name == "summary-prompt":
            command.add_argument(
                "--companies", action="store_true", help="Also acquire configured employer/job context and prepare each prompt"
            )

    configuration = commands.add_parser("config", help="Validate local configuration without a captured profile")
    config_commands = configuration.add_subparsers(dest="config_command", required=True)
    lint = config_commands.add_parser("lint", help="Validate configuration schemas and merged settings without capture or rendering")
    lint.add_argument("paths", type=Path, nargs="*", metavar="PATH", help="Config files to validate; defaults to --config")

    site = commands.add_parser("site", help="Prepare a GitHub Pages site in .cache/pages from the existing PDF")
    site.add_argument("--repository", help="Publishing OWNER/REPO; defaults to GITHUB_REPOSITORY or the local Git origin")

    ownership = commands.add_parser("publish-ownership", help="Update live LinkedIn About with a signed release's public key identity")
    ownership.add_argument("--public-key", type=Path, required=True, help="Release cosign.pub path relative to the current directory")
    ownership.add_argument("--dry-run", action="store_true", help="Read and preview About without submitting any changes")
    ownership.add_argument("--headless", action="store_true", help="Use LinkedIn login environment variables without a desktop")
    ownership.add_argument("--connect-port", type=int, help="Attach to an explicitly opened local Firefox Marionette port")

    resume = commands.add_parser("publish-resume", help="Upload a release PDF to LinkedIn's saved application resumes")
    resume.add_argument("--pdf", type=Path, required=True, help="Verified release PDF relative to the configuration directory")
    resume.add_argument("--dry-run", action="store_true", help="Check the PDF, account, and upload form without uploading")
    resume.add_argument("--headless", action="store_true", help="Use LinkedIn login environment variables without a desktop")
    resume.add_argument("--connect-port", type=int, help="Attach to an existing local Firefox Marionette port")

    skills_prompt = commands.add_parser("skills-prompt", help="Prepare an evidence-backed Codex skill proposal for the checked-out tag")
    skills_prompt.add_argument("--tag", required=True, help="Existing Git tag pointing to the checked-out commit")
    skills = commands.add_parser("publish-skills", help="Add missing proposed skills to LinkedIn without changing existing skills")
    skills.add_argument("--suggestions", type=Path, required=True, help="Generated skills JSON relative to the configuration directory")
    skills.add_argument("--tag", required=True, help="Existing Git tag matching the proposal and checked-out commit")
    skills.add_argument("--dry-run", action="store_true", help="Compare with live skills and print additions without saving")
    skills.add_argument("--headless", action="store_true", help="Use LinkedIn login environment variables without a desktop")
    skills.add_argument("--connect-port", type=int, help="Attach to an existing local Firefox Marionette port")

    args = parser.parse_args(argv)

    # Install error reporting before reading user configuration, and release its handler after every invocation.
    with logging_context():
        return _run(args)


def _lint_configs(paths: Sequence[Path]) -> int:
    """
    Validate each requested configuration independently without loading profile data or producing artifacts.

    Args:
        paths (Sequence[Path]): Configuration filenames relative to the working directory, or absolute paths.

    Returns:
        int: Zero when every config passes, otherwise two after reporting all invalid files.
    """
    result = 0

    # Pre-commit supplies a batch of filenames; a broken config must not prevent diagnostics for the remaining files.
    for path in paths:
        try:
            load_config(path)
        except (OSError, ValueError, ValidationError, yaml.YAMLError) as error:
            # Report the field path and concise schema message rather than dumping the full config into hook output.
            detail = f"{error.json_path}: {error.message}" if isinstance(error, ValidationError) else str(error)
            _LOGGER.error("Invalid configuration %s: %s", path, detail, extra={"file.path": str(path), "error.type": type(error).__name__})
            result = 2
        else:
            print(f"Valid configuration: {path}")

    return result


def _run(args: argparse.Namespace) -> int:
    """
    Execute a parsed command inside its caller-owned logging context.

    Args:
        args (argparse.Namespace): Parsed CLI arguments and selected command.

    Returns:
        int: Zero on success, two on failure, or 130 on user cancellation.
    """
    try:
        override = args.log_level or os.environ.get("RESUMEME_LOG_LEVEL")

        if override:
            set_log_level(override)

        # Config lint accepts pre-commit's filenames and must run before the ordinary pipeline opens its snapshot.
        if args.command == "config":
            return _lint_configs(args.paths or [args.config])

        # Anchor every stage to the config directory, regardless of where the command was invoked.
        config = load_config(args.config)
        set_log_level(override or config.logging.level)
        _LOGGER.info("Starting command", extra={"resumeme.command": args.command})
        _LOGGER.debug("Configuration loaded", extra={"file.path": str(args.config), "resumeme.command": args.command})
        root = args.config.resolve().parent
        snapshot = project_path(root, config.output.profile)

        # Prefer the profile's display name, while allowing release-only recovery to fall back to the configured username.
        if args.command == "publish-resume":
            profile_name = load_profile(snapshot, config.linkedin.username).name if snapshot.is_file() else config.linkedin.username
            filename = publish_resume(
                config,
                root,
                project_path(root, str(args.pdf)),
                profile_name=profile_name,
                dry_run=args.dry_run,
                headless=args.headless,
                connect_port=args.connect_port,
            )
            print(("Upload preview: " if args.dry_run else "Confirmed saved resume: ") + filename)

            if config.linkedin.resume.share_with_recruiters is not None:
                state = "enabled" if config.linkedin.resume.share_with_recruiters else "disabled"
                print(("Recruiter sharing requested: " if args.dry_run else "Confirmed recruiter sharing: ") + state)

            return 0

        # Skill publication validates the tagged proposal before opening the browser or changing live profile state.
        if args.command == "publish-skills":
            names = publish_skills(
                config,
                root,
                project_path(root, str(args.suggestions)),
                args.tag,
                dry_run=args.dry_run,
                headless=args.headless,
                connect_port=args.connect_port,
            )
            print(("Proposed additions: " if args.dry_run else "Confirmed additions: ") + (", ".join(names) or "none"))
            return 0

        # Ownership maintenance reads the live editor; it does not depend on a snapshot or rewrite generated résumé content.
        if args.command == "publish-ownership":
            about = publish_ownership(
                config, root, args.public_key, dry_run=args.dry_run, headless=args.headless, connect_port=args.connect_port
            )
            print(about if args.dry_run else "Confirmed the public signing identity in LinkedIn About.")
            return 0

        if args.command in {"capture", "enrich"}:
            profile = (
                capture_profile(config, root, args.connect_port, headless=args.headless)
                if args.command == "capture"
                else cache_media(load_profile(snapshot, config.linkedin.username), config, root)
            )

            if profile.warnings and not args.allow_incomplete:
                # Preserve recoverable diagnostics without replacing the last accepted, publishable snapshot.
                diagnostic = root / ".cache/capture/profile.json"
                save_profile(profile, diagnostic)
                raise ProfileError(f"Capture needs review at {diagnostic}: " + "; ".join(profile.warnings))

            save_profile(profile, snapshot)
            _LOGGER.info("Saved profile snapshot", extra={"file.path": str(snapshot), "profile.sections": len(profile.sections)})
            print(f"Saved {snapshot}")
            return 0

        # Enforce ownership on every offline path so a fork cannot accidentally publish the previous owner's resume.
        profile = load_profile(snapshot, config.linkedin.username)

        if args.command == "skills-prompt":
            print(prepare_skills(profile, config, root, args.tag))
            return 0

        if args.command == "site":
            # Resolve the actual publishing repository without inheriting a release URL override from an upstream fork.
            releases = release_destination(Ownership(repository=args.repository), root)
            repository = releases.removeprefix("https://github.com/").removesuffix("/releases")
            print(build_site(profile, config, root, repository))
            return 0

        if args.command == "summary-prompt":
            print(prepare_summary(profile, config, root))

            if args.companies:
                for directory in prepare_companies(profile, config, root):
                    print(directory)

            return 0

        if args.command == "validate":
            if profile.warnings and not args.allow_incomplete:
                raise ProfileError("Capture warnings: " + "; ".join(profile.warnings))

            print(f"Valid profile: {profile.name} ({len(profile.sections)} sections)")
            return 0

        # Optional public activity is acquired once before the offline compiler; explicit snapshots support repeatable builds.
        contributions = None

        if args.github_calendar:
            if not config.github.contributions.enabled:
                raise ConfigurationError("Enable github.contributions before supplying --github-calendar.")

            contributions = load_calendar(project_path(root, str(args.github_calendar)))
        elif config.github.contributions.enabled:
            contributions = fetch_calendar(config)

        # Rendering owns content selection; compilation only consumes the resulting TeX and staged assets.
        source = render_profile(
            profile,
            config,
            root,
            allow_incomplete=args.allow_incomplete,
            summary_path=project_path(root, str(args.summary)) if args.summary else None,
            contributions=contributions,
        )
        result = compile_pdf(source, config, root) if args.command == "build" else source
        print(result)

        # Variants share the capture and reuse matching calendars; per-job overrides may request a different public activity window.
        if args.company_summaries:
            for result in render_companies(
                profile,
                config,
                root,
                project_path(root, str(args.company_summaries)),
                compile_documents=args.command == "build",
                contributions=contributions,
            ):
                print(result)
    except KeyboardInterrupt:
        # Browser cleanup happens in its context manager; retain the profile so the next capture can reuse login.
        _LOGGER.error("Browser operation cancelled; the local login is retained. Check live About if a Save was in progress.")
        return 130
    except NoSuchWindowException:
        _LOGGER.error("The browser window was closed. Rerun the command and leave the capture browser open until it finishes.")
        return 2
    except TimeoutException as error:
        _LOGGER.error("LinkedIn timed out. %s", error.msg or "Rerun the command; increase capture.page_timeout_seconds if needed.")
        _LOGGER.debug("Browser timeout details", exc_info=True)
        return 2
    except (
        ResumemeError,
        OSError,
        ValueError,
        RuntimeError,
        ValidationError,
        yaml.YAMLError,
        WebDriverException,
        subprocess.TimeoutExpired,
    ) as error:
        _LOGGER.error("%s", error, extra={"error.type": type(error).__name__})
        _LOGGER.debug("Command failure details", exc_info=True)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
