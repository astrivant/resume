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

from resumeme.config import load_config, project_path
from resumeme.latex.compilation import compile_pdf
from resumeme.latex.rendering import render_profile
from resumeme.linkedin.browser import capture_profile
from resumeme.linkedin.media import cache_media
from resumeme.models import load_profile, save_profile

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
        ("capture", "Open Firefox, wait for login, and save your expanded profile and images"),
        ("enrich", "Discover text links, resolve destinations, and cache previews from the saved profile"),
        ("validate", "Validate configuration and snapshot ownership"),
        ("render", "Generate tex/resume.tex from the saved profile"),
        ("build", "Render LaTeX and compile resume.pdf with Docker or the bundled container toolchain"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument(
            "--allow-incomplete", action="store_true", help="Explicitly accept recorded capture warnings or missing images"
        )

        if name == "capture":
            command.add_argument("--connect-port", type=int, help="Attach to an explicitly opened local Firefox Marionette port")

    args = parser.parse_args(argv)

    try:
        # Anchor every stage to the config directory, regardless of where the command was invoked.
        config = load_config(args.config)
        root = args.config.resolve().parent
        snapshot = project_path(root, config.output.profile)

        if args.command in {"capture", "enrich"}:
            profile = (
                capture_profile(config, root, args.connect_port)
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

        if args.command == "validate":
            if profile.warnings and not args.allow_incomplete:
                raise ValueError("Capture warnings: " + "; ".join(profile.warnings))

            print(f"Valid profile: {profile.name} ({len(profile.sections)} sections)")
            return 0

        # Rendering owns content selection; compilation only consumes the resulting TeX and staged assets.
        source = render_profile(profile, config, root, allow_incomplete=args.allow_incomplete)
        result = compile_pdf(source, config, root) if args.command == "build" else source
        print(result)
    except KeyboardInterrupt:
        # Browser cleanup happens in its context manager; retain the profile so the next capture can reuse login.
        print("\nresumeme: Capture cancelled; the local browser login is retained for next time.", file=sys.stderr)
        return 130
    except NoSuchWindowException:
        print(
            "resumeme: The capture window was closed. Run `resumeme capture` again and leave Firefox open until capture finishes.",
            file=sys.stderr,
        )
        return 2
    except TimeoutException:
        print("resumeme: LinkedIn page loading timed out. Retry capture; increase capture.page_timeout_seconds if needed.", file=sys.stderr)
        return 2
    except (OSError, ValueError, RuntimeError, ValidationError, yaml.YAMLError, WebDriverException, subprocess.TimeoutExpired) as error:
        print(f"resumeme: {error}", file=sys.stderr)
        return 2

    return 0
