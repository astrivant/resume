"""
Expose the explicit About-update opt-in to the release workflow.
"""

from __future__ import annotations

import os
from pathlib import Path

from resumeme.config import load_config

config = load_config(Path("resumeme.config.yaml"))

# Keep disabled forks independent of browser credentials and signed artifact downloads.
with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
    output.write(f"enabled={str(config.linkedin.ownership.update_about).lower()}\n")
