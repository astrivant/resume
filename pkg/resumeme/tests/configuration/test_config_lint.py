"""
Verify config-only CLI validation and the reusable pre-commit hook contract.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest
import yaml

from resumeme.cli import main
from resumeme.tests.paths import REPOSITORY_ROOT

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import CaptureFixture, MonkeyPatch


def test_lint_accepts_multiple_paths_without_snapshot_or_default_config(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """
    Validate arbitrary filenames before the pipeline attempts to load its default config or a saved profile.

    Args:
        tmp_path (Path): Directory with configs but no saved profile or runtime assets.
        monkeypatch (MonkeyPatch): Set working directory and forbid profile loading.
        capsys (CaptureFixture[str]): Captured CLI output.

    Returns:
        None: Both files are validated without mutations, even when the global config path does not exist.
    """
    paths = [tmp_path / "resumeme.config.yaml", tmp_path / "custom profile.yml"]

    for path in paths:
        path.write_text("linkedin: {username: example-person}\n")

    before = {path: path.read_bytes() for path in paths}
    profile = Mock(side_effect=AssertionError("Config lint must not open a profile"))
    monkeypatch.setattr("resumeme.cli.load_profile", profile)
    monkeypatch.chdir(tmp_path)
    assert main(["--config", "missing-default.yaml", "config", "lint", *(path.name for path in paths)]) == 0
    output = capsys.readouterr()
    assert all(f"Valid configuration: {path.name}" in output.out for path in paths)
    assert output.err == ""
    assert {path: path.read_bytes() for path in paths} == before
    assert set(tmp_path.iterdir()) == set(paths)
    profile.assert_not_called()


@pytest.mark.parametrize("explicit", [False, True])
def test_lint_defaults_to_selected_config(tmp_path: Path, monkeypatch: MonkeyPatch, explicit: bool) -> None:
    """
    Honor the global config selector when no positional filenames are supplied.

    Args:
        tmp_path (Path): Config-only working directory.
        monkeypatch (MonkeyPatch): Isolate the CLI's working directory.
        explicit (bool): Select a custom path or the standard default filename.

    Returns:
        None: Either invocation succeeds without a profile snapshot.
    """
    name = "chosen.yaml" if explicit else "resumeme.config.yaml"
    (tmp_path / name).write_text("linkedin: {username: example-person}\n")
    monkeypatch.chdir(tmp_path)
    assert main([*(["--config", name] if explicit else []), "config", "lint"]) == 0


@pytest.mark.parametrize(
    "invalid",
    [
        "",
        "linkedin: [",
        "linkedin: {username: example-person}\nstyle: {display_websites: 'false'}\n",
        "linkedin: {username: example-person}\nstyle: {theme: unknown}\n",
        "linkedin: {username: example-person}\ncodex:\n  companies:\n    - username: example\n"
        "      job_url: https://www.linkedin.com/jobs/view/123/\n      overrides:\n        style: {font_size: 9}\n",
    ],
)
def test_lint_reports_all_failed_files_and_continues(tmp_path: Path, capsys: CaptureFixture[str], invalid: str) -> None:
    """
    Return failure for malformed or invalid settings while validating the rest of a pre-commit batch.

    Args:
        tmp_path (Path): Independent config files.
        capsys (CaptureFixture[str]): Captured OpenTelemetry errors and successful filenames.
        invalid (str): Invalid YAML, schema values, or merged configuration constraints.

    Returns:
        None: Diagnostics identify both failed filenames and the valid trailing file is still checked.
    """
    broken, missing, valid = [tmp_path / name for name in ("invalid.yaml", "missing.yaml", "valid.yaml")]
    broken.write_text(invalid)
    valid.write_text("linkedin: {username: example-person}\n")
    assert main(["config", "lint", str(broken), str(missing), str(valid)]) == 2
    output = capsys.readouterr()
    records = [json.loads(line) for line in output.out.splitlines() if line.startswith("{")]
    assert [record["attributes"]["file.path"] for record in records] == [str(broken), str(missing)]
    assert all(record["severity_text"] == "ERROR" for record in records)
    assert f"Valid configuration: {valid}" in output.out
    assert output.err == ""


def test_schema_diagnostic_identifies_field_without_dumping_config(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    """
    Report a schema field path without printing unrelated private configuration context.

    Args:
        tmp_path (Path): Config directory.
        capsys (CaptureFixture[str]): Captured error record.

    Returns:
        None: The failure identifies the bad style value without including other fields.
    """
    path = tmp_path / "invalid.yaml"
    path.write_text("linkedin: {username: example-person}\nstyle: {display_websites: 'false'}\ncodex: {context: PRIVATE_CONTEXT}\n")
    assert main(["config", "lint", str(path)]) == 2
    output = capsys.readouterr().out
    assert "$.style.display_websites" in output and "PRIVATE_CONTEXT" not in output


def test_module_entry_point_and_hook_selection(tmp_path: Path) -> None:
    """
    Exercise the checkout's module launcher and ensure published hook defaults match both config files.

    Args:
        tmp_path (Path): Config-only directory outside the checkout.

    Returns:
        None: Module invocation succeeds, both named configs match the hook, and unrelated YAML is excluded.
    """
    config = tmp_path / "other.yaml"
    config.write_text("linkedin: {username: example-person}\n")
    result = subprocess.run(
        [sys.executable, "-m", "resumeme.cli", "config", "lint", str(config)], cwd=tmp_path, text=True, capture_output=True, check=False
    )
    assert result.returncode == 0 and f"Valid configuration: {config}" in result.stdout
    root = REPOSITORY_ROOT
    hook = yaml.safe_load((root / ".pre-commit-hooks.yaml").read_text())[0]
    assert hook["id"] == "resumeme-config-validator" and hook["entry"] == "resumeme config lint"
    assert hook["language"] == "python" and hook.get("pass_filenames", True)
    assert hook["types"] == ["yaml"]

    for path in ("resumeme.config.yaml", "resumeme.config.ref.yaml", "profiles/resumeme.config.work.yml"):
        assert re.search(hook["files"], path)

    assert not re.search(hook["files"], ".github/workflows/ci.yml")
