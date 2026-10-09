"""
Verify consistent bullet presentation without changing prose or captured content.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from resumeme.compiler.asts.profile import Entry, Link, Profile, Section
from resumeme.compiler.passes.lists import TextBlock, text_blocks
from resumeme.compiler.pipeline import render_profile
from resumeme.config import Config, LinkedIn

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
        "\u2013",
        "\u2014",
        "\u2212",
        "\u2022",
        "\u2023",
        "\u25e6",
        "\u25aa",
        "\u25cb",
        "\u25c6",
        "\u2192",
        "\u27a4",
        "->",
        "=>",
        "\u2713",
        "\u2610",
        "\u2705",
        "\U0001f539",
        "[x]",
        "- [ ]",
        "1.",
        "2)",
        "(3)",
        "a)",
        "(iv)",
        "\u2460",
        "1\ufe0f\u20e3",
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


@pytest.mark.parametrize("marker", ["\u2022", "\u25aa", "\U0001f539", "\u2705", "\u2611\ufe0f"])
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
        "\u221210 degrees",
        "1.2.3 release",
        "C++ services",
        "Built X \u2014 then Y",
        "https://example.org/a-b",
        "A. Smith",
        "I. Introduction",
        "o rings",
        "-",
        "\u2022",
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
    paragraphs = [
        "Responsibilities",
        "  - Parent\n    \u2022 Child\n      continued text\n  + Sibling",
        "",
        "A. First",
        "B. Second",
        "Summary",
    ]
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


@pytest.mark.parametrize("separator", ["\n", "\r\n", None])
def test_unindented_sentence_fragments_stay_in_the_same_bullet(separator: str | None) -> None:
    """
    Reflow comma and semicolon continuations from HTML breaks or separate captured rows.

    Args:
        separator (str | None): Embedded newline style, or None for separate paragraph strings.

    Returns:
        None: One nested bullet owns the complete sentence without changing the input.
    """
    fragments = ["  \u2022 Providing technical reviews,", "coordinating platform work;", "guiding implementation decisions."]
    paragraphs = ["- Responsibilities", *([separator.join(fragments)] if separator is not None else fragments), "- Next item"]
    original = paragraphs.copy()
    assert text_blocks(paragraphs) == [
        TextBlock("Responsibilities", 0),
        TextBlock("Providing technical reviews, coordinating platform work; guiding implementation decisions.", 1),
        TextBlock("Next item", 0),
    ]
    assert paragraphs == original


@pytest.mark.parametrize(
    ("previous", "following"),
    [
        ("Providing technical reviews,", "Responsibilities"),
        ("Providing technical reviews,", "responsibilities:"),
        ("Providing technical reviews,", "2020 - Present"),
        ("Providing technical reviews,", "https://example.org/project"),
        ("Providing technical reviews,", "www.example.org/project"),
        ("Provided technical reviews.", "coordinating platform work"),
        ("Provided technical reviews!", "coordinating platform work"),
        ("Provided technical reviews?", "coordinating platform work"),
        ("Responsibilities:", "coordinating platform work"),
        ("TLS certificates", "pre-commit hook that lints Gitlab CI configurations"),
    ],
)
def test_unmarked_headings_metadata_and_attachments_remain_separate(previous: str, following: str) -> None:
    """
    Require positive sentence-continuation evidence before joining unindented content.

    Args:
        previous (str): Bullet text preceding a potential boundary.
        following (str): Content that must retain its own paragraph.

    Returns:
        None: Adjacent prose is not mistaken for a wrapped fragment.
    """
    assert text_blocks([f"- {previous}", following]) == [TextBlock(previous, 0), TextBlock(following)]


@pytest.mark.parametrize("blank", ["", " ", "\n"])
def test_blank_lines_end_sentence_continuations(blank: str) -> None:
    """
    Treat an explicit blank line as a paragraph boundary even after a comma.

    Args:
        blank (str): Blank paragraph or embedded line break.

    Returns:
        None: Later prose cannot resume a terminated list item.
    """
    assert text_blocks(["- Providing technical reviews,", blank, "coordinating platform work."]) == [
        TextBlock("Providing technical reviews,", 0),
        TextBlock("coordinating platform work."),
    ]


def test_new_bullets_and_ordinary_paragraphs_keep_their_boundaries() -> None:
    """
    Preserve explicit list markers and independent prose despite continuation-like punctuation.

    Returns:
        None: Only unmarked continuations inside an active list can join the previous item.
    """
    assert text_blocks(["- Providing reviews,", "- coordinating work."]) == [
        TextBlock("Providing reviews,", 0),
        TextBlock("coordinating work.", 0),
    ]
    assert text_blocks(["Providing reviews,", "coordinating work."]) == [
        TextBlock("Providing reviews,"),
        TextBlock("coordinating work."),
    ]


def test_rendered_experience_rejoins_the_captured_sentence(tmp_path: Path) -> None:
    """
    Keep the reported role description in one bullet while retaining escaping, links, and source rows.

    Args:
        tmp_path (Path): Isolated template output directory.

    Returns:
        None: LaTeX controls natural wrapping instead of starting a paragraph mid-sentence.
    """
    lines = [
        "- Led and mentored engineers by overseeing project execution, providing technical reviews,",
        "coordinating platform work, guiding implementation decisions, and supporting team skill set growth.",
        r"- Documented changes,",
        r"including \input{secret} & https://lnkd.in/tool.",
    ]
    original = lines.copy()
    entry = Entry("Lead Platform Engineer", lines, [Link("Tool", "https://lnkd.in/tool", "https://example.org/tool")])
    profile = Profile("example-person", "Alex", sections=[Section("experience", "Experience", [entry])])
    source = render_profile(profile, Config(LinkedIn(profile.username)), tmp_path).read_text()
    assert rf"\profilebullet{{0}}{{{lines[0][2:]} {lines[1]}}}" in source
    assert r"\profileparagraph{coordinating platform work" not in source
    assert r"\profilebullet{0}{Documented changes, including \textbackslash{}input\{secret\} \& \href{https://example.org/tool}" in source
    assert entry.paragraphs == original


def test_rendered_bullets_preserve_links_and_escape_profile_text(tmp_path: Path) -> None:
    """
    Translate lists at render time while keeping source data, hyperlink targets, and TeX escaping intact.

    Args:
        tmp_path (Path): Isolated template output directory.

    Returns:
        None: Original markers become consistent LaTeX bullet commands without becoming executable TeX.
    """
    lines = ["\u2014 Built \\input{secret} & tooling", "  \u25aa Read https://lnkd.in/tool", "2020 - Present"]
    entry = Entry("Responsibilities", lines, [Link("Tool", "https://lnkd.in/tool", "https://example.org/tool")])
    profile = Profile("example-person", "Alex", sections=[Section("about", "About", [entry])])
    source = render_profile(profile, Config(LinkedIn(profile.username)), tmp_path).read_text()
    assert r"\profilebullet{0}{Built \textbackslash{}input\{secret\} \& tooling}" in source
    assert r"\profilebullet{1}{Read \href{https://example.org/tool}" in source
    assert r"\profileparagraph{2020 - Present}" in source
    assert profile.sections[0].entries[0].paragraphs == lines
