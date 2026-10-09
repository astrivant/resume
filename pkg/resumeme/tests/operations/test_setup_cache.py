"""
Check CI cache isolation, installation decisions, and current-source binding without registry access.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest
import yaml

from resumeme.tests.paths import REPOSITORY_ROOT

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def setup_checkout(tmp_path: Path) -> Path:
    """
    Copy only setup inputs into an isolated checkout with command-recording tools.

    Args:
        tmp_path (Path): Temporary checkout root.

    Returns:
        Path: Checkout safe for real shell execution and cache-input edits.
    """
    paths = [".tool-versions", "poetry.lock", "pyproject.toml"]

    for folder in ("scripts/tooling", ".github/actions/setup-poetry", ".github/actions/setup-project"):
        paths.extend(str(path.relative_to(REPOSITORY_ROOT)) for path in (REPOSITORY_ROOT / folder).iterdir() if path.is_file())

    for name in paths:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPOSITORY_ROOT / name, target)

    # Separate Poetry's own interpreter from the project's environment just as the composite actions do.
    for name in ("commands/python", "commands/poetry", "tooling/bin/python", "tooling/bin/poetry", ".venv/bin/python"):
        executable = tmp_path / name
        executable.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPOSITORY_ROOT / "pkg/resumeme/tests/fixtures/ci-command.sh", executable)
        executable.chmod(0o700)

    return tmp_path


def run_setup(checkout: Path, script: str, **overrides: str) -> subprocess.CompletedProcess[str]:
    """
    Execute a setup script against recording tools and isolated GitHub environment files.

    Args:
        checkout (Path): Disposable checkout holding setup scripts and stub executables.
        script (str): Tooling script basename.
        **overrides (str): Explicit cache/group/validation inputs for this invocation.

    Returns:
        subprocess.CompletedProcess[str]: Bounded execution with captured diagnostics.
    """
    environment = dict(
        os.environ,
        PATH=f"{checkout / 'commands'}{os.pathsep}{os.environ['PATH']}",
        SETUP_CALLS=str(checkout / "calls"),
        POETRY_ENVIRONMENT=str(checkout / "tooling"),
        POETRY_VERSION="2.5.1",
        GITHUB_PATH=str(checkout / "github-path"),
        GITHUB_ENV=str(checkout / "github-env"),
    )
    environment.update(overrides)
    return subprocess.run(
        ["bash", f"scripts/tooling/{script}"], cwd=checkout, env=environment, capture_output=True, text=True, check=False, timeout=30
    )


@pytest.mark.parametrize("hit", ["true", "false", ""])
def test_poetry_cache_hit_skips_bootstrap(setup_checkout: Path, hit: str) -> None:
    """
    Skip pip and venv creation only after an exact Poetry cache restore.

    Args:
        setup_checkout (Path): Isolated executable recorder.
        hit (str): GitHub cache-hit output, including an absent cache.

    Returns:
        None: Warm paths perform no installation and cold paths install the pinned version.
    """
    result = run_setup(setup_checkout, "setup-poetry.sh", POETRY_CACHE_HIT=hit)
    assert result.returncode == 0, result.stderr
    calls = (setup_checkout / "calls").read_text().splitlines()
    assert calls[-1] == "poetry --version"

    if hit == "true":
        assert calls == ["poetry --version"]
    else:
        assert calls[:2] == [
            f"python -m venv {setup_checkout / 'tooling'}",
            "python -m pip install --disable-pip-version-check poetry==2.5.1",
        ]

    assert (setup_checkout / "github-path").read_text().strip() == str(setup_checkout / "tooling/bin")
    assert "POETRY_INSTALLER_RE_RESOLVE=false" in (setup_checkout / "github-env").read_text()


@pytest.mark.parametrize("groups", ["main", "main,dev"])
@pytest.mark.parametrize("hit", ["true", "false", ""])
def test_project_restore_validates_lock_and_only_installs_on_miss(setup_checkout: Path, groups: str, hit: str) -> None:
    """
    Retain lockfile checks on warm paths and synchronize only the requested groups on cold paths.

    Args:
        setup_checkout (Path): Isolated executable recorder.
        groups (str): Runtime or development cache partition.
        hit (str): GitHub cache-hit output.

    Returns:
        None: Warm dependency environments require no registry-facing command.
    """
    result = run_setup(setup_checkout, "setup-env.sh", DEPENDENCY_GROUPS=groups, PROJECT_CACHE_HIT=hit)
    assert result.returncode == 0, result.stderr
    calls = (setup_checkout / "calls").read_text().splitlines()
    expected = ["poetry check --lock"]

    if hit != "true":
        expected.append(f"poetry sync --only {groups} --no-root --no-interaction --no-ansi")

    assert calls == expected


def test_invalid_lock_or_group_stops_before_installation(setup_checkout: Path) -> None:
    """
    Reject invalid setup inputs even when Actions reports a cache hit.

    Args:
        setup_checkout (Path): Isolated executable recorder.

    Returns:
        None: No installation follows a lockfile failure or unsupported group.
    """
    invalid_group = run_setup(setup_checkout, "setup-env.sh", DEPENDENCY_GROUPS="arbitrary", PROJECT_CACHE_HIT="true")
    assert invalid_group.returncode == 2
    assert not (setup_checkout / "calls").exists()
    invalid_lock = run_setup(setup_checkout, "setup-env.sh", SETUP_LOCK_VALID="false", PROJECT_CACHE_HIT="true")
    assert invalid_lock.returncode != 0
    assert (setup_checkout / "calls").read_text().splitlines() == ["poetry check --lock"]


def cache_key(checkout: Path, kind: str = "project", groups: str = "main,dev") -> str:
    """
    Run the production cache-key generator with fixed temporary-runner paths.

    Args:
        checkout (Path): Checkout whose files and absolute path identify an environment.
        kind (str): Poetry or project environment selector.
        groups (str): Selected dependency groups.

    Returns:
        str: Opaque exact-match cache key.
    """
    result = subprocess.run(
        [sys.executable, "scripts/tooling/cache-keys.py", kind],
        cwd=checkout,
        env=dict(os.environ, RUNNER_TEMP=str(checkout.parent / "runner"), DEPENDENCY_GROUPS=groups),
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return dict(line.split("=", 1) for line in result.stdout.splitlines())["key"]


@pytest.mark.parametrize(
    "name", ["poetry.lock", "pyproject.toml", "scripts/tooling/setup-env.sh", ".github/actions/setup-project/action.yml"]
)
def test_dependency_changes_invalidate_project_but_preserve_poetry(setup_checkout: Path, name: str) -> None:
    """
    Refresh installed packages when their contract changes without redownloading Poetry.

    Args:
        setup_checkout (Path): Isolated cache inputs.
        name (str): Dependency or project installation input to change.

    Returns:
        None: Only the project cache is invalidated.
    """
    project_before = cache_key(setup_checkout)
    poetry_before = cache_key(setup_checkout, "poetry")
    path = setup_checkout / name
    path.write_text(path.read_text() + "\n# Changed installation contract\n")
    assert cache_key(setup_checkout) != project_before
    assert cache_key(setup_checkout, "poetry") == poetry_before


def test_cache_reuses_dependencies_across_source_edits_but_isolates_paths_and_groups(setup_checkout: Path) -> None:
    """
    Keep cache reuse independent of application edits while preventing incompatible environment restores.

    Args:
        setup_checkout (Path): Isolated cache inputs.

    Returns:
        None: Source edits preserve the key; dependency group, checkout path, and Poetry pin changes do not.
    """
    original = cache_key(setup_checkout)
    poetry_before = cache_key(setup_checkout, "poetry")
    (setup_checkout / "source.py").write_text("CURRENT_SOURCE = 'new commit'\n")
    (setup_checkout / "resumeme.config.yaml").write_text("linkedin: {username: another-person}\n")
    assert cache_key(setup_checkout) == original
    assert cache_key(setup_checkout, groups="main") != original
    moved = setup_checkout / "another-checkout"
    moved.mkdir()

    for path in (".tool-versions", "poetry.lock", "pyproject.toml", "scripts", ".github"):
        source = setup_checkout / path

        if source.is_dir():
            shutil.copytree(source, moved / path)
        else:
            shutil.copyfile(source, moved / path)

    assert cache_key(moved) != original
    pins = setup_checkout / ".tool-versions"
    pins.write_text("\n".join("poetry 0.0.0" if line.startswith("poetry ") else line for line in pins.read_text().splitlines()) + "\n")
    assert cache_key(setup_checkout) != original
    assert cache_key(setup_checkout, "poetry") != poetry_before


def test_cache_save_precedes_current_source_install_and_uses_exact_keys() -> None:
    """
    Protect the orchestration contract that cached environments contain dependencies rather than a previous checkout.

    Returns:
        None: Both caches save immediately, forbid partial restores, and project binding is unconditional and local.
    """
    for kind in ("project", "poetry"):
        action = yaml.safe_load((REPOSITORY_ROOT / f".github/actions/setup-{kind}/action.yml").read_text())
        steps = action["runs"]["steps"]
        restores = [step for step in steps if step.get("uses", "").startswith("actions/cache/restore@")]
        saves = [step for step in steps if step.get("uses", "").startswith("actions/cache/save@")]
        assert len(restores) == len(saves) == 1
        assert "restore-keys" not in restores[0]["with"]
        assert saves[0]["with"]["key"] == "${{ steps.cache.outputs.cache-primary-key }}"
        assert saves[0]["with"]["path"] == restores[0]["with"]["path"]

        if kind == "project":
            bind = steps[-1]
            assert "if" not in bind
            assert shlex.split(bind["run"]) == ["poetry", "install", "--only-root", "--no-interaction", "--no-ansi"]
            assert steps.index(saves[0]) < steps.index(bind)


def test_restored_dependencies_bind_current_source_offline(tmp_path: Path) -> None:
    """
    Restore a real Poetry environment and expose edited application code through its current package entry point.

    Args:
        tmp_path (Path): Disposable dependency-free package and environment archive.

    Returns:
        None: Restoring and rebinding the package works without an upstream package registry.
    """
    poetry = shutil.which("poetry")

    if poetry is None:
        pytest.skip("This integration check requires the Poetry CLI used by CI setup.")

    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "pyproject.toml").write_text(
        '[project]\nname = "cache-fixture"\nversion = "1.0.0"\nrequires-python = ">=3.13"\n'
        '[project.scripts]\ncache-fixture = "cache_fixture:main"\n'
        '[tool.poetry.dependencies]\npython = ">=3.13"\n'
        "[tool.poetry.group.dev.dependencies]\n"
        '[build-system]\nrequires = ["poetry-core==2.5.0"]\nbuild-backend = "poetry.core.masonry.api"\n'
    )
    package = checkout / "cache_fixture"
    package.mkdir()
    source = package / "__init__.py"
    source.write_text('def main():\n    print("old checkout")\n')
    environment = dict(
        os.environ,
        POETRY_VIRTUALENVS_IN_PROJECT="true",
        POETRY_KEYRING_ENABLED="false",
        POETRY_INSTALLER_RE_RESOLVE="false",
        DEPENDENCY_GROUPS="main",
        PROJECT_CACHE_HIT="false",
        PIP_NO_INDEX="1",
        HTTP_PROXY="http://127.0.0.1:1",
        HTTPS_PROXY="http://127.0.0.1:1",
        NO_PROXY="",
    )
    environment.pop("VIRTUAL_ENV", None)
    environment.pop("CONDA_PREFIX", None)
    commands = [
        [sys.executable, "-m", "venv", str(checkout / ".venv")],
        [poetry, "lock", "--no-interaction"],
        ["bash", str(REPOSITORY_ROOT / "scripts/tooling/setup-env.sh")],
    ]

    for command in commands:
        result = subprocess.run(command, cwd=checkout, env=environment, capture_output=True, text=True, check=False, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr

    # Archive only dependencies, matching the save point in the action; the restored path remains identical for venv shebangs.
    archived = tmp_path / "environment-cache"
    shutil.copytree(checkout / ".venv", archived, symlinks=True)
    shutil.rmtree(checkout / ".venv")
    shutil.copytree(archived, checkout / ".venv", symlinks=True)
    source.write_text('def main():\n    print("current checkout")\n')
    environment["PROJECT_CACHE_HIT"] = "true"
    action = yaml.safe_load((REPOSITORY_ROOT / ".github/actions/setup-project/action.yml").read_text())
    bind = shlex.split(action["runs"]["steps"][-1]["run"])

    for command in (["bash", str(REPOSITORY_ROOT / "scripts/tooling/setup-env.sh")], bind):
        result = subprocess.run(command, cwd=checkout, env=environment, capture_output=True, text=True, check=False, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr

    result = subprocess.run(
        [str(checkout / ".venv/bin/cache-fixture")], cwd=checkout, capture_output=True, text=True, check=True, timeout=30
    )
    assert result.stdout.strip() == "current checkout"
