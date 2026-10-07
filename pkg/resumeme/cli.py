"""
Provide explicit capture, validation, rendering, and PDF build commands.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from jsonschema import ValidationError
from selenium.common.exceptions import NoSuchWindowException, TimeoutException, WebDriverException

from resumeme.codex.companies import prepare_companies, render_companies
from resumeme.codex.request import prepare_summary
from resumeme.compiler.asts.contributions import load_calendar
from resumeme.compiler.asts.profile import load_profile, save_profile
from resumeme.compiler.backends.latex.compilation import compile_pdf
from resumeme.compiler.pipeline import render_profile
from resumeme.config import load_config, project_path
from resumeme.github.contributions import fetch_calendar
from resumeme.linkedin.browser import capture_profile
from resumeme.linkedin.media import cache_media
from resumeme.linkedin.ownership import publish_ownership

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["main"]


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
            command.add_argument("--headless", action="store_true", help="Capture unattended using LINKEDIN_USERNAME and LINKEDIN_PASSWORD")

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

    ownership = commands.add_parser("publish-ownership", help="Update live LinkedIn About with a signed release's public key identity")
    ownership.add_argument("--public-key", type=Path, required=True, help="Release cosign.pub path relative to the current directory")
    ownership.add_argument("--dry-run", action="store_true", help="Read and preview About without submitting any changes")
    ownership.add_argument("--headless", action="store_true", help="Use LINKEDIN_USERNAME and LINKEDIN_PASSWORD without a desktop")
    ownership.add_argument("--connect-port", type=int, help="Attach to an explicitly opened local Firefox Marionette port")

    args = parser.parse_args(argv)

    try:
        # Anchor every stage to the config directory, regardless of where the command was invoked.
        config = load_config(args.config)
        root = args.config.resolve().parent
        snapshot = project_path(root, config.output.profile)

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
                raise ValueError(f"Capture needs review at {diagnostic}: " + "; ".join(profile.warnings))

            save_profile(profile, snapshot)
            print(f"Saved {snapshot}")
            return 0

        # Enforce ownership on every offline path so a fork cannot accidentally publish the previous owner's resume.
        profile = load_profile(snapshot, config.linkedin.username)

        if args.command == "summary-prompt":
            print(prepare_summary(profile, config, root))

            if args.companies:
                for directory in prepare_companies(profile, config, root):
                    print(directory)

            return 0

        if args.command == "validate":
            if profile.warnings and not args.allow_incomplete:
                raise ValueError("Capture warnings: " + "; ".join(profile.warnings))

            print(f"Valid profile: {profile.name} ({len(profile.sections)} sections)")
            return 0

        # Optional public activity is acquired once before the offline compiler; explicit snapshots support repeatable builds.
        contributions = None

        if args.github_calendar:
            if not config.github.contributions.enabled:
                raise ValueError("Enable github.contributions before supplying --github-calendar.")

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

        # All variants share the same capture and calendar; explicit response bundles keep ordinary builds offline.
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
        print(
            "\nresumeme: Browser operation cancelled; the local login is retained. Check live About if a Save was in progress.",
            file=sys.stderr,
        )
        return 130
    except NoSuchWindowException:
        print(
            "resumeme: The browser window was closed. Rerun the command and leave the capture browser open until it finishes.",
            file=sys.stderr,
        )
        return 2
    except TimeoutException:
        print("resumeme: LinkedIn timed out. Rerun the command; increase capture.page_timeout_seconds if needed.", file=sys.stderr)
        return 2
    except (OSError, ValueError, RuntimeError, ValidationError, yaml.YAMLError, WebDriverException, subprocess.TimeoutExpired) as error:
        print(f"resumeme: {error}", file=sys.stderr)
        return 2

    return 0
