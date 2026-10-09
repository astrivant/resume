"""
Exercise real pytest workers and coverage files to prevent gaps or duplication across CI shards.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING
from xml.etree import ElementTree

import pytest
from coverage import Coverage, CoverageData

from resumeme.tests.paths import REPOSITORY_ROOT

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def shard_suite(tmp_path: Path) -> Path:
    """
    Create an isolated parameterized suite using the repository's actual collection hooks.

    Args:
        tmp_path (Path): Temporary suite root, separate from the current pytest invocation.

    Returns:
        Path: Suite with eleven distinct cases and independently measurable source lines.
    """
    shutil.copyfile(REPOSITORY_ROOT / "conftest.py", tmp_path / "conftest.py")
    (tmp_path / "sample.py").write_text(
        "def identify(value):\n" + "".join(f"    if value == {value}:\n        return {value}\n" for value in range(11))
    )
    (tmp_path / "test_sample.py").write_text(
        "import pytest\nfrom sample import identify\n\n"
        '@pytest.mark.parametrize("value", range(11))\n'
        "def test_identify(value):\n    assert identify(value) == value\n"
    )
    (tmp_path / ".coveragerc").write_text("[run]\nrelative_files = True\nsource = sample\n")
    (tmp_path / "shards").mkdir()
    return tmp_path


def run_shard(suite: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """
    Invoke real pytest without inheriting the parent run's options or coverage destination.

    Args:
        suite (Path): Isolated collection root.
        *arguments (str): Explicit pytest options for the child process.

    Returns:
        subprocess.CompletedProcess[str]: Bounded child execution with its exit status and diagnostic output.
    """
    environment = dict(os.environ, PYTEST_ADDOPTS="", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", COVERAGE_FILE=str(suite / ".coverage"))
    environment.pop("COVERAGE_PROCESS_START", None)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "xdist.plugin", "-p", "pytest_cov.plugin", "-q", *arguments],
        cwd=suite,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def test_shards_execute_every_case_once_and_combine_coverage(shard_suite: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Execute three disjoint shards through xdist and merge their real coverage data.

    Args:
        shard_suite (Path): Parameterized suite with eleven cases, intentionally not divisible by three.
        monkeypatch (pytest.MonkeyPatch): Sets the source root for relative coverage paths during aggregation.

    Returns:
        None: All cases run once, shard sizes differ by at most one, and aggregation preserves every executed source line.
    """
    partitions: list[set[str]] = []
    measured: set[int] = set()

    # Run the actual hooks in multiple workers to catch nondeterministic collection as well as partitioning errors.
    for index in range(1, 4):
        report = shard_suite / f"junit-{index}.xml"
        result = run_shard(
            shard_suite,
            "-n",
            "2",
            "--shard-count",
            "3",
            "--shard-index",
            str(index),
            "--cov=sample",
            "--cov-report=",
            f"--junitxml={report}",
        )
        assert result.returncode == 0, result.stdout + result.stderr
        partitions.append({case.attrib["name"] for case in ElementTree.parse(report).iter("testcase")})
        data_path = shard_suite / "shards" / f".coverage.shard-{index}"
        (shard_suite / ".coverage").rename(data_path)
        data = CoverageData(basename=str(data_path))
        data.read()
        measured.update(data.lines("sample.py") or [])

    assert set.union(*partitions) == {f"test_identify[{value}]" for value in range(11)}
    assert sum(map(len, partitions)) == 11
    assert sorted(map(len, partitions)) == [3, 4, 4]

    # Use coverage's production merge API, preserving each distinct return statement across runner data files.
    monkeypatch.chdir(shard_suite)
    combined = Coverage(config_file=str(shard_suite / ".coveragerc"), data_file=str(shard_suite / ".coverage"))
    combined.combine(data_paths=[str(shard_suite / "shards")], strict=True, keep=True)
    combined.save()
    assert set(combined.get_data().lines("sample.py") or []) == measured
    assert set(range(3, 24, 2)) <= measured


@pytest.mark.parametrize("count,index", [(0, 1), (-1, 1), (3, 0), (3, 4)])
def test_invalid_shards_fail_before_collection(shard_suite: Path, count: int, index: int) -> None:
    """
    Reject misconfigured matrices instead of silently selecting no tests or an incomplete partition.

    Args:
        shard_suite (Path): Isolated suite whose cases must not execute for invalid settings.
        count (int): Invalid total count or count paired with an invalid index.
        index (int): Requested one-based shard.

    Returns:
        None: Pytest reports a usage error before any case runs.
    """
    result = run_shard(shard_suite, "-n", "0", "--shard-count", str(count), "--shard-index", str(index))
    assert result.returncode == pytest.ExitCode.USAGE_ERROR
    assert "Sharding requires" in result.stderr


def test_default_run_keeps_the_entire_suite(shard_suite: Path) -> None:
    """
    Keep ordinary local pytest invocations complete when no shard options are supplied.

    Args:
        shard_suite (Path): Isolated parameterized suite.

    Returns:
        None: The unchanged local command executes all eleven cases.
    """
    result = run_shard(shard_suite, "-n", "0")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "11 passed" in result.stdout
