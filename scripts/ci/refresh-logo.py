"""
Render the README logo from the same source revision used by résumé publication.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from resumeme.visualization.branding import render_logo


def main() -> None:
    """
    Accept an explicit revision so local previews and CI retries share one deterministic renderer.

    Returns:
        None: The project logo is rendered; Git staging remains the publication script's responsibility.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", required=True, help="Source commit SHA, or another stable seed for a local preview.")
    parser.add_argument("--output", type=Path, default=Path("docs/assets/branding/resumeme-logo.png"))
    arguments = parser.parse_args()
    render_logo(Path("docs/assets/branding"), arguments.output, arguments.seed)


if __name__ == "__main__":
    main()
