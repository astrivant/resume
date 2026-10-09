"""
Identify reusable CI environments without tying dependency caches to a source commit.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import sysconfig
from pathlib import Path


def cache_settings(kind: str) -> dict[str, str]:
    """
    Build exact cache keys for installed tools or locked project dependencies.

    Args:
        kind (str): Either poetry or project, selecting the environment contract.

    Returns:
        dict[str, str]: Cache key, absolute environment path, and pinned Poetry version.

    Raises:
        ValueError: The environment kind or dependency group is unsupported.
    """
    if kind not in {"poetry", "project"}:
        raise ValueError("Environment kind must be poetry or project.")

    groups = os.environ.get("DEPENDENCY_GROUPS", "main,dev")

    if groups not in {"main", "main,dev"}:
        raise ValueError("DEPENDENCY_GROUPS must be main or main,dev.")

    workspace = Path.cwd().resolve()
    tooling = Path(os.environ["RUNNER_TEMP"]).resolve() / "resumeme-poetry"
    version = next(line.split()[1] for line in Path(".tool-versions").read_text().splitlines() if line.startswith("poetry "))
    release = Path("/etc/os-release")

    # Venvs contain absolute shebangs and interpreter links; equal Python versions alone do not make them portable.
    compatibility = {
        "system": platform.system(),
        "release": release.read_text() if release.exists() else platform.mac_ver()[0],
        "architecture": platform.machine(),
        "python": sys.version,
        "abi": sysconfig.get_config_var("SOABI"),
        "interpreter": sys.executable,
        "prefix": sys.base_prefix,
        "workspace": str(workspace),
        "tooling": str(tooling),
        "poetry": version,
    }
    digest = hashlib.sha256(json.dumps(compatibility, sort_keys=True).encode())
    files = [Path(__file__), Path("scripts/tooling/setup-poetry.sh"), Path(".github/actions/setup-poetry/action.yml")]

    if kind == "project":
        digest.update(groups.encode())
        files.extend(
            Path(name)
            for name in ("poetry.lock", "pyproject.toml", "scripts/tooling/setup-env.sh", ".github/actions/setup-project/action.yml")
        )

    # Installation logic participates in invalidation; application source edits keep compatible dependency caches warm.
    for path in files:
        digest.update(path.name.encode())
        digest.update(path.read_bytes())

    return {
        "key": f"resumeme-{kind}-v1-{digest.hexdigest()}",
        "path": str(tooling if kind == "poetry" else workspace / ".venv"),
        "version": version,
    }


if __name__ == "__main__":
    for name, value in cache_settings(sys.argv[1]).items():
        print(f"{name}={value}")
