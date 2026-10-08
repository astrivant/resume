"""
Render the README logo from the same source revision used by résumé publication.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from resumeme.config import load_config
from resumeme.github.readme import update_project_branding
from resumeme.visualization.branding import render_logo


def main() -> None:
    """
    Accept an explicit revision so local previews and CI retries share one deterministic renderer.

    Returns:
        None: The logo and optional dated branding are rendered; Git staging remains the publication script's responsibility.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", required=True, help="Source commit SHA, or another stable seed for a local preview.")
    parser.add_argument("--output", type=Path, default=Path("docs/assets/branding/resumeme-logo.png"))
    parser.add_argument(
        "--brew-date", type=date.fromisoformat, help="UTC build date (YYYY-MM-DD); also refresh the badge and README branding."
    )
    arguments = parser.parse_args()
    render_logo(Path("docs/assets/branding"), arguments.output, arguments.seed)

    if arguments.brew_date is not None:
        update_project_branding(Path.cwd(), load_config(Path("resumeme.config.yaml")), arguments.brew_date)


if __name__ == "__main__":
    main()
