"""
Verify that LinkedIn approval records help correlate a request without exposing credentials or session data.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from resumeme.linkedin.approval_audit import record_approval_context

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import CaptureFixture, MonkeyPatch


def test_approval_context_is_printed_and_retained_without_secrets(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """
    Include public workflow context in live output and the Actions summary, excluding login secrets and checkpoint URLs.

    Args:
        tmp_path (Path): Isolated step summary destination.
        monkeypatch (MonkeyPatch): Synthetic workflow metadata and credentials.
        capsys (CaptureFixture[str]): Captured stdout for secret-leak assertions.

    Returns:
        None: Both records contain matching run identifiers and only approved metadata.
    """
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/resumeme")
    monkeypatch.setenv("GITHUB_WORKFLOW", "Build resume")
    monkeypatch.setenv("GITHUB_JOB", "capture-linkedin")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("GITHUB_REF", "refs/tags/resume-2026-10")
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    monkeypatch.setenv("GITHUB_RUN_ID", "123456")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    monkeypatch.setenv("LINKEDIN_USERNAME", "private-login@example.org")
    monkeypatch.setenv("LINKEDIN_PASSWORD", "synthetic-password")

    record_approval_context(
        profile_username="https://www.linkedin.com/in/example-person/?trk=private",
        browser="firefox",
        checkpoint="approval",
        timeout_seconds=900,
    )

    output = capsys.readouterr().out
    retained = summary.read_text(encoding="utf-8")

    for content in (output, retained):
        assert "example-person" in content
        assert "Build resume" in content
        assert "capture-linkedin" in content
        assert "refs/tags/resume-2026-10" in content
        assert "a" * 12 in content
        assert "123456" in content
        assert "attempt 2" in content
        assert "https://github.com/example/resumeme/actions/runs/123456" in content
        assert "private-login@example.org" not in content
        assert "synthetic-password" not in content
        assert "private" not in content

    assert "firefox" in output and "approval" in output
    assert "[Open workflow run](https://github.com/example/resumeme/actions/runs/123456)" in retained


def test_workflow_metadata_is_single_line_and_markdown_escaped(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """
    Keep unexpected line breaks and table delimiters inside one harmless field.

    Args:
        tmp_path (Path): Isolated step summary destination.
        monkeypatch (MonkeyPatch): Synthetic workflow values, including malformed display text.
        capsys (CaptureFixture[str]): Captured stdout for newline assertions.

    Returns:
        None: The metadata cannot add forged lines or Markdown table cells.
    """
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/resumeme")
    monkeypatch.setenv("GITHUB_WORKFLOW", "refresh | injected\nforged row [click](https://evil.example)")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_SHA", "not-a-commit")
    monkeypatch.setenv("GITHUB_RUN_ID", "123")

    record_approval_context(profile_username="example-person", browser="chrome", checkpoint="approval", timeout_seconds=900)

    output = capsys.readouterr().out
    retained = summary.read_text(encoding="utf-8")
    assert "refresh | injected forged row" in output
    assert "| Workflow | refresh &#124; injected forged row &#91;click&#93;(https://evil.example) |" in retained
    assert not any(line.startswith("forged row") for line in retained.splitlines())
    assert "[click](https://evil.example)" not in retained
    assert "not-a-commit" not in retained


def test_local_approval_context_does_not_require_a_step_summary(monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]) -> None:
    """
    Print useful local approval context when the Actions summary environment is absent.

    Args:
        monkeypatch (MonkeyPatch): Removes the optional workflow summary setting.
        capsys (CaptureFixture[str]): Captured local output.

    Returns:
        None: The local sign-in wait continues without writing a retained summary.
    """
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    record_approval_context(profile_username="example-person", browser="firefox", checkpoint="approval", timeout_seconds=900)

    assert "LinkedIn sign-in audit context" in capsys.readouterr().out
