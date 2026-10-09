"""
Resolve generated LaTeX and report paths for the TeXtidote container action.
"""

from __future__ import annotations

import os
from pathlib import Path

from resumeme.config import load_config, project_path

# Match the compiler's working directory so relative inputs in custom templates resolve beside the generated document.
root = Path.cwd()
config = load_config(root / "resumeme.config.yaml")
source = project_path(root, config.output.tex)

if not source.is_file():
    raise FileNotFoundError(f"Render the configured LaTeX source before running TeXtidote: {source}")

# Keep reports outside generated-source directories so custom output paths share the same artifact upload contract.
report = root / ".cache/textidote/resume.html"
report.parent.mkdir(parents=True, exist_ok=True)

with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
    output.write(f"tex_file={source.name}\n")
    output.write(f"tex_directory={source.parent.relative_to(root).as_posix()}\n")
    output.write(f"tex_report={os.path.relpath(report, source.parent)}\n")
