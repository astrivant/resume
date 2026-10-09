"""
Verify Trivy report redaction and the safe summaries consumed by GitHub Actions.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import TYPE_CHECKING

from resumeme.tests.paths import REPOSITORY_ROOT

if TYPE_CHECKING:
    from pathlib import Path


TRIVY_REPORT_SCRIPT = REPOSITORY_ROOT / "scripts/ci/checks/trivy-report.py"


def test_prepare_redacts_secret_values_and_retains_vulnerability_details(tmp_path: Path) -> None:
    """
    Keep useful report metadata while removing secret matches and source snippets before upload.

    Args:
        tmp_path (Path): Isolated report and output directory.

    Returns:
        None: The report artifact and job summary contain no matched secret value or source excerpt.
    """
    matched_secret = "TRIVY_SECRET_SENTINEL_DO_NOT_PUBLISH"
    source_excerpt = "TRIVY_SOURCE_SENTINEL_DO_NOT_PUBLISH"
    raw_report = tmp_path / "raw.json"
    sanitized_report = tmp_path / "sanitized.json"
    summary = tmp_path / "summary.md"
    github_output = tmp_path / "github-output.txt"
    raw_report.write_text(
        json.dumps(
            {
                "Results": [
                    {
                        "Target": "pkg/example.py",
                        "Secrets": [
                            {
                                "RuleID": "private-key",
                                "Category": "AsymmetricPrivateKey",
                                "Severity": "HIGH",
                                "Title": "Private key",
                                "StartLine": 12,
                                "Match": matched_secret,
                                "Code": {"Lines": [{"Number": 12, "Content": source_excerpt}]},
                            }
                        ],
                        "Vulnerabilities": [
                            {
                                "VulnerabilityID": "CVE-2026-1234",
                                "PkgName": "sample-library",
                                "InstalledVersion": "1.0.0",
                                "FixedVersion": "1.0.1",
                                "Severity": "CRITICAL",
                                "Title": "Example dependency vulnerability",
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(TRIVY_REPORT_SCRIPT),
            "prepare",
            "--input",
            str(raw_report),
            "--report-output",
            str(sanitized_report),
            "--summary-output",
            str(summary),
            "--github-output",
            str(github_output),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    serialized_report = sanitized_report.read_text(encoding="utf-8")
    summary_text = summary.read_text(encoding="utf-8")
    assert matched_secret not in serialized_report + summary_text
    assert source_excerpt not in serialized_report + summary_text
    assert "<redacted>" in serialized_report
    assert "CVE-2026-1234" in serialized_report
    assert "sample-library" in summary_text
    assert "2 findings" in summary_text
    output_text = github_output.read_text(encoding="utf-8")
    assert "available=true" in output_text
    assert "finding_count=2" in output_text


def test_comment_sanitizes_untrusted_report_and_links_full_results(tmp_path: Path) -> None:
    """
    Sanitize downloaded artifact data again before including finding metadata in a PR comment.

    Args:
        tmp_path (Path): Isolated artifact and comment payload directory.

    Returns:
        None: The comment is concise, contains the results link, and excludes matched content and snippets.
    """
    matched_secret = "TRIVY_COMMENT_SENTINEL_DO_NOT_PUBLISH"
    source_excerpt = "TRIVY_COMMENT_SOURCE_DO_NOT_PUBLISH"
    artifact = tmp_path / "trivy-report.json"
    comment = tmp_path / "comment.json"
    artifact.write_text(
        json.dumps(
            {
                "Results": [
                    {
                        "Target": "pkg/example.py",
                        "Secrets": [
                            {
                                "RuleID": "token-rule",
                                "Severity": "HIGH",
                                "Title": "Credential pattern",
                                "StartLine": 7,
                                "Match": matched_secret,
                                "Code": {"Lines": [{"Content": source_excerpt}]},
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(TRIVY_REPORT_SCRIPT),
            "comment",
            "--input",
            str(artifact),
            "--output",
            str(comment),
            "--artifact-url",
            "https://github.com/example/project/actions/runs/10/artifacts/20",
            "--run-url",
            "https://github.com/example/project/actions/runs/10",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(comment.read_text(encoding="utf-8"))
    body = payload["body"]
    assert "<!-- resumeme-trivy-scan -->" in body
    assert "1 finding" in body
    assert "Full scan results" in body
    assert "actions/runs/10/artifacts/20" in body
    assert matched_secret not in body
    assert source_excerpt not in body


def test_prepare_marks_missing_report_as_a_gate_failure(tmp_path: Path) -> None:
    """
    Distinguish scanner failures from clean scans so missing reports cannot pass the required check.

    Args:
        tmp_path (Path): Isolated output directory with no scanner report.

    Returns:
        None: The report output explicitly marks the scan unavailable and the finding count unknown.
    """
    github_output = tmp_path / "github-output.txt"

    result = subprocess.run(
        [
            sys.executable,
            str(TRIVY_REPORT_SCRIPT),
            "prepare",
            "--input",
            str(tmp_path / "missing.json"),
            "--report-output",
            str(tmp_path / "sanitized.json"),
            "--summary-output",
            str(tmp_path / "summary.md"),
            "--github-output",
            str(github_output),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "Trivy scan report unavailable" in (tmp_path / "summary.md").read_text(encoding="utf-8")
    output_text = github_output.read_text(encoding="utf-8")
    assert "available=false" in output_text
    assert "finding_count=-1" in output_text
