"""
Expose validated Pages settings without making deployment decisions from raw YAML.
"""

from __future__ import annotations

import os
from hashlib import sha256
from pathlib import Path

from resumeme.config import load_config, project_path

config = load_config(Path("resumeme.config.yaml"))
settings = config.pages

# Schema validation keeps every output on one line; disabled forks never create a Pages deployment.
with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
    output.write(f"enabled={str(settings.enabled).lower()}\n")
    output.write(f"path={settings.path}\n")
    output.write(f"custom-domain={settings.custom_domain or ''}\n")

    # Bind post-deployment verification to this accepted PDF, independent of the triggering branch or tag SHA.
    if settings.enabled:
        digest = sha256(project_path(Path.cwd(), config.output.pdf).read_bytes()).hexdigest()
        output.write(f"pdf-sha256={digest}\n")
