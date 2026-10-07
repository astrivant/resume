"""
Verify consistent bullet presentation without changing prose or captured content.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from resumeme.config import Config, LinkedIn
from resumeme.latex.lists import TextBlock, text_blocks
from resumeme.latex.rendering import render_profile
from resumeme.models import Entry, Link, Profile, Section

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    "marker",
    [
        "-",
        "--",
        "---",
        "*",
        "+",
        "–",
        "—",
        "−",
        "•",
        "‣",
        "◦",
        "▪",
        "○",
        "◆",
        "→",
        "➤",
        "->",
        "=>",
        "✓",
        "☐",
        "✅",
        "🔹",
        "[x]",
        "- [ ]",
        "1.",
        "2)",
        "(3)",
        "a)",
        "(iv)",
        "①",
        "1️⃣",
    ],
)
def test_common_list_markers_become_regular_bullets(marker: str) -> None:
    """
    Recognize common text-editor and Unicode list styles at the beginning of a line.

    Args:
        marker (str): Original visible list prefix.

    Returns:
        None: Only the marker changes; the item's content remains literal.
    """
    assert text_blocks([f"{marker} Built Python services & APIs."]) == [TextBlock("Built Python services & APIs.", 0)]


@pytest.mark.parametrize("marker", ["•", "▪", "🔹", "✅", "☑️"])
def test_unambiguous_unicode_markers_need_no_separator(marker: str) -> None:
    """
    Accept pasted Unicode bullets whose source omitted the usual separating space.

    Args:
        marker (str): Unambiguous typographic or emoji marker.

    Returns:
        None: The marker is normalized even when it touches the first word.
    """
    assert text_blocks([f"{marker}Delivered services"]) == [TextBlock("Delivered services", 0)]


@pytest.mark.parametrize(
    "line",
    [
        "2020 - Present",
        "2026. Led a team",
        "2026-10-07",
        "-5% error rate",
        "−10 degrees",
        "1.2.3 release",
        "C++ services",
        "Built X — then Y",
        "https://example.org/a-b",
        "A. Smith",
        "I. Introduction",
        "o rings",
        "-",
        "•",
    ],
)
def test_ordinary_prose_and_ambiguous_prefixes_are_preserved(line: str) -> None:
    """
    Protect dates, numeric values, technical terms, and isolated initials from false list detection.

    Args:
        line (str): Non-list prose or an incomplete marker.

    Returns:
        None: The complete input remains an ordinary paragraph.
    """
    assert text_blocks([line]) == [TextBlock(line)]


def test_nested_items_continuations_and_paragraph_boundaries() -> None:
    """
    Retain nesting and explicitly indented continuation text while keeping headings separate.

    Returns:
        None: Mixed list markers share stable indentation and unmarked headings terminate the list.
    """
    paragraphs = ["Responsibilities", "  - Parent\n    • Child\n      continued text\n  + Sibling", "", "A. First", "B. Second", "Summary"]
    assert text_blocks(paragraphs) == [
        TextBlock("Responsibilities"),
        TextBlock("Parent", 0),
        TextBlock("Child continued text", 1),
        TextBlock("Sibling", 0),
        TextBlock("First", 0),
        TextBlock("Second", 0),
        TextBlock("Summary"),
    ]
    assert paragraphs[1].startswith("  - Parent")


def test_rendered_bullets_preserve_links_and_escape_profile_text(tmp_path: Path) -> None:
    """
    Translate lists at render time while keeping source data, hyperlink targets, and TeX escaping intact.

    Args:
        tmp_path (Path): Isolated template output directory.

    Returns:
        None: Original markers become consistent LaTeX bullet commands without becoming executable TeX.
    """
    lines = [r"— Built \input{secret} & tooling", "  ▪ Read https://lnkd.in/tool", "2020 - Present"]
    entry = Entry("Responsibilities", lines, [Link("Tool", "https://lnkd.in/tool", "https://example.org/tool")])
    profile = Profile("example-person", "Alex", sections=[Section("about", "About", [entry])])
    source = render_profile(profile, Config(LinkedIn(profile.username)), tmp_path).read_text()
    assert r"\profilebullet{0}{Built \textbackslash{}input\{secret\} \& tooling}" in source
    assert r"\profilebullet{1}{Read \href{https://example.org/tool}" in source
    assert r"\profileparagraph{2020 - Present}" in source
    assert profile.sections[0].entries[0].paragraphs == lines
