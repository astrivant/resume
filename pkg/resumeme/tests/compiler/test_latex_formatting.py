"""
Verify readable LaTeX source formatting and generated section markers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from resumeme.compiler.asts.profile import Entry, Profile, Section
from resumeme.compiler.backends.latex.formatting import format_tex_source
from resumeme.compiler.pipeline import render_profile
from resumeme.config import Config, LinkedIn

if TYPE_CHECKING:
    from pathlib import Path


def test_format_tex_source_preserves_commands_and_collapses_blank_lines() -> None:
    """
    Normalize blank lines without changing any nonblank source line.

    Returns:
        None: Leading and repeated blank lines are removed, and one final newline remains.
    """

    source = "\n\n\\documentclass{article}\n\n\n% Section\n  \t\n\\begin{document}\n\n"

    assert format_tex_source(source) == "\\documentclass{article}\n\n% Section\n\n\\begin{document}\n"


def test_rendered_tex_has_source_sections_and_normalized_spacing(tmp_path: Path) -> None:
    """
    Mark generated content blocks and emit no long blank-line runs.

    Args:
        tmp_path (Path): Isolated rendering directory.

    Returns:
        None: The rendered source is navigable and whitespace-normalized.
    """

    profile = Profile("example-person", "Alex Example", sections=[Section("about", "About", [Entry("A short profile.")])])

    source = render_profile(profile, Config(LinkedIn(profile.username)), tmp_path).read_text(encoding="utf-8")
    lines = source.splitlines()
    blank_run = 0

    for line in lines:
        blank_run = blank_run + 1 if not line.strip() else 0
        assert blank_run <= 1

    assert source.startswith("% =============================================================================\n% Document class")
    assert "% First-page profile, contact details, and contents navigation" in source
    assert "% Resume section: about" in source
    assert source.endswith("\\end{document}\n")
