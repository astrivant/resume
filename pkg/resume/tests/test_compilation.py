"""
Verify both compiler backends preserve existing PDFs until two successful passes finish.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from resume.config import Config, LinkedIn
from resume.latex.compilation import compile_pdf

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch


@pytest.mark.parametrize("backend", ["docker", "local"])
def test_compiler_backends_publish_after_both_passes(tmp_path: Path, monkeypatch: MonkeyPatch, backend: str) -> None:
    """
    Use the configured toolchain while preserving source-relative assets and atomic publication.

    Args:
        tmp_path (Path): Temporary project directory.
        monkeypatch (MonkeyPatch): Scoped compiler and environment replacements.
        backend (str): Docker on the host or pdfLaTeX bundled in the runtime image.

    Returns:
        None: Both passes use deterministic metadata and only the completed PDF replaces the destination.
    """
    source = tmp_path / "tex" / "custom.tex"
    source.parent.mkdir()
    source.write_text("Test input", encoding="utf-8")
    destination = tmp_path / "resume.pdf"
    # Seed a published document so the fake compiler can assert it remains untouched throughout both passes.
    destination.write_bytes(b"previous PDF")
    monkeypatch.setenv("RESUME_TEX_BACKEND", backend)
    calls: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        """
        Simulate a compiler pass and check the publication contract at its boundary.

        Args:
            command (list[str]): Executable and compiler arguments.
            **kwargs (object): Working directory, environment, and bounded subprocess options.

        Returns:
            subprocess.CompletedProcess[str]: Successful compiler output.
        """
        assert command[0] == ("docker" if backend == "docker" else "pdflatex")
        assert command[-1] == "custom.tex"
        assert "-no-shell-escape" in command
        assert kwargs["cwd"] == source.parent
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        assert environment["SOURCE_DATE_EPOCH"] == "946684800"
        assert environment["FORCE_SOURCE_DATE"] == "1"
        assert kwargs["timeout"] == 120
        assert destination.read_bytes() == b"previous PDF"
        calls.append(command)
        output = next(path for path in (tmp_path / ".cache/build").iterdir() if path.is_dir())
        (output / "custom.pdf").write_bytes(b"%PDF-1.7\ncompiled")
        return subprocess.CompletedProcess(command, 0, stdout="compiler output", stderr="")

    monkeypatch.setattr("resume.latex.compilation.subprocess.run", run)
    assert compile_pdf(source, Config(LinkedIn("example-person")), tmp_path) == destination
    assert len(calls) == 2
    assert destination.read_bytes() == b"%PDF-1.7\ncompiled"
    assert (tmp_path / ".cache/build/pdflatex-2.log").read_text() == "compiler output"


@pytest.mark.parametrize("failure", ["exit", "timeout", "missing", "invalid"])
def test_failed_local_compilation_preserves_existing_pdf(tmp_path: Path, monkeypatch: MonkeyPatch, failure: str) -> None:
    """
    Keep previous output intact after a failed second pass, timeout, or missing valid PDF.

    Args:
        tmp_path (Path): Temporary project directory.
        monkeypatch (MonkeyPatch): Scoped compiler replacement.
        failure (str): Failure mode to inject.

    Returns:
        None: Failed compilation never publishes partial or invalid output.
    """
    source = tmp_path / "resume.tex"
    source.write_text("Test input", encoding="utf-8")
    destination = tmp_path / "resume.pdf"
    destination.write_bytes(b"previous PDF")
    monkeypatch.setenv("RESUME_TEX_BACKEND", "local")
    calls = 0

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        """
        Inject one compiler failure without starting an external process.

        Args:
            command (list[str]): Compiler executable and arguments.
            **kwargs (object): Subprocess controls.

        Returns:
            subprocess.CompletedProcess[str]: Simulated success or failure status.

        Raises:
            subprocess.TimeoutExpired: The timeout scenario reaches its second pass.
        """
        nonlocal calls
        calls += 1
        if calls == 2 and failure == "timeout":
            raise subprocess.TimeoutExpired(command, 120)
        output = next(path for path in (tmp_path / ".cache/build").iterdir() if path.is_dir())
        if failure != "missing":
            (output / "resume.pdf").write_bytes(b"corrupt" if failure == "invalid" else b"%PDF-partial")
        return subprocess.CompletedProcess(command, int(calls == 2 and failure == "exit"), stdout="", stderr="compiler diagnostic")

    monkeypatch.setattr("resume.latex.compilation.subprocess.run", run)
    # Check failure at the publication boundary, not just the subprocess result: no partial document may replace the prior PDF.
    with pytest.raises(subprocess.TimeoutExpired if failure == "timeout" else RuntimeError):
        compile_pdf(source, Config(LinkedIn("example-person")), tmp_path)
    assert destination.read_bytes() == b"previous PDF"
    assert not destination.with_suffix(".pending.pdf").exists()


def test_unknown_compiler_backend_is_rejected(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Fail visibly when a misspelled backend would otherwise select an unintended compiler.

    Args:
        tmp_path (Path): Temporary project directory.
        monkeypatch (MonkeyPatch): Scoped backend selection.

    Returns:
        None: Invalid configuration fails before executing a compiler.
    """
    monkeypatch.setenv("RESUME_TEX_BACKEND", "typo")
    with pytest.raises(ValueError, match="RESUME_TEX_BACKEND"):
        compile_pdf(tmp_path / "resume.tex", Config(LinkedIn("example-person")), tmp_path)
