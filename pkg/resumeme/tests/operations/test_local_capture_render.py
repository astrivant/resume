"""
Verify the local capture-to-render path used before a manual repository push.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from resumeme.cli import main
from resumeme.compiler.asts.profile import Entry, Profile, Section

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch


def test_local_capture_then_render_formats_tex_before_manual_push(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Persist a locally authenticated capture and render its formatted source offline.

    Args:
        tmp_path (Path): Isolated fork directory containing the config and generated files.
        monkeypatch (MonkeyPatch): Replaces only the browser interaction with a known captured profile.

    Returns:
        None: The normal local CLI sequence writes a clean TeX file from its saved profile.
    """

    config = tmp_path / "resumeme.config.yaml"
    config.write_text("linkedin:\n  username: example-person\n", encoding="utf-8")
    captured = Profile("example-person", "Alex Example", sections=[Section("about", "About", [Entry("A short profile.")])])

    # Keep the test local while exercising the same CLI persistence path as interactive browser capture.
    monkeypatch.setattr("resumeme.cli.capture_profile", lambda *_args, **_kwargs: captured)

    assert main(["--config", str(config), "capture"]) == 0
    assert (tmp_path / "data/profile.json").is_file()
    assert main(["--config", str(config), "validate"]) == 0
    assert main(["--config", str(config), "render"]) == 0

    source = (tmp_path / "tex/resume.tex").read_text(encoding="utf-8")
    blank_run = 0

    for line in source.splitlines():
        blank_run = blank_run + 1 if not line.strip() else 0
        assert blank_run <= 1

    assert "% Resume section: about" in source
