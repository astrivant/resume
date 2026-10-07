"""
Preserve paragraph ownership from LinkedIn HTML through LaTeX without forced breaks around inline content.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml
from jsonschema import ValidationError

from resumeme.compiler.asts.parsing import parse_detail
from resumeme.compiler.asts.profile import Entry, Profile, Section
from resumeme.compiler.constants.lists import BODY_HEADINGS
from resumeme.compiler.passes.headings import is_body_heading
from resumeme.compiler.passes.lists import TextBlock, text_blocks
from resumeme.compiler.pipeline import render_profile
from resumeme.config import Config, Experience, LinkedIn, Style, load_config

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("section", ["experience", "about", "projects", "featured"])
def test_inline_html_and_soft_breaks_render_as_complete_body_blocks(tmp_path: Path, section: str) -> None:
    """
    Capture inline elements without introducing paragraphs or breaking words, punctuation, and URLs.

    Args:
        tmp_path (Path): Isolated LaTeX output directory.
        section (str): Profile content owner exercising the shared capture and rendering path.

    Returns:
        None: Each complete bullet or prose paragraph reaches LaTeX once, with links and escaping intact.
    """
    html = (
        "<main><div data-resume-entry><h3>Engineering work</h3><p>Example Company</p>"
        "<p>Jan 2024 - Present</p><p>Responsibilities:<br>"
        "- Built reli<strong>able</strong> systems using<br>AWS and <em>Python</em>.<br>"
        "Improved availability.<br>- Read "
        '<a href="https://example.org/tool"><span>https://example.org/</span>tool</a>, '
        r"using \input{secret} &amp; documentation.<span>…see more</span></p>"
        "<p>Collaborated with <span>engineers</span><br>across teams.<br><br>Kept a separate paragraph.</p>"
        "<p>Another independent paragraph.</p></div></main>"
    )
    parsed = parse_detail(html, section, section.title())
    entry = parsed.entries[0]
    original = entry.paragraphs.copy()
    expected = [
        TextBlock("Example Company"),
        TextBlock("Jan 2024 - Present"),
        TextBlock("Responsibilities:"),
        TextBlock("Built reliable systems using AWS and Python. Improved availability.", 0),
        TextBlock(r"Read https://example.org/tool, using \input{secret} & documentation.", 0),
        TextBlock("Collaborated with engineers across teams."),
        TextBlock("Kept a separate paragraph."),
        TextBlock("Another independent paragraph."),
    ]
    assert text_blocks(entry.paragraphs) == expected
    assert entry.links[0].url == "https://example.org/tool"

    # The shared backend must consume the captured block structure without adding explicit linebreak commands.
    profile = Profile("example-person", "Alex", sections=[parsed])
    source = render_profile(profile, Config(LinkedIn(profile.username), project_filter=None), tmp_path).read_text()
    assert r"\profilebullet{0}{Built reliable systems using AWS and Python. Improved availability.}" in source
    assert r"\profileparagraph{Collaborated with engineers across teams.}" in source
    assert r"\profileparagraph{Kept a separate paragraph.}" in source
    assert r"\href{https://example.org/tool}" in source
    assert r"\textbackslash{}input\{secret\} \& documentation." in source
    assert entry.paragraphs == original


@pytest.mark.parametrize("separator", ["\n", "\r\n", "\u2028"])
@pytest.mark.parametrize("marker", ["", "- ", "  • "])
def test_multiline_body_text_reflows_without_sentence_heuristics(separator: str, marker: str) -> None:
    """
    Join soft wraps even without commas, lowercase continuation text, or an unfinished sentence.

    Args:
        separator (str): Captured line separator within a single body paragraph.
        marker (str): Optional bullet marker and nesting whitespace.

    Returns:
        None: One paragraph or list item owns all its words; explicit blank lines remain boundaries.
    """
    body = separator.join([marker + "Built systems using", "AWS, Python & Go.", "Improved availability."])
    assert text_blocks([body, "", "A separate paragraph."]) == [
        TextBlock("Built systems using AWS, Python & Go. Improved availability.", 0 if marker else None),
        TextBlock("A separate paragraph."),
    ]


def test_body_breaks_keep_nested_lists_headings_dates_and_independent_paragraphs() -> None:
    """
    Keep structural text separate while allowing a nested bullet to continue with uppercase technical names.

    Returns:
        None: Date rows, headings, blank lines, sibling paragraphs, and list depth retain their meaning.
    """
    assert text_blocks(
        [
            "2020 - Present\nResponsibilities\n- Built services\n  • using\nAWS and Go\n- Next item\nTechnologies\nPython",
            "A separate sentence,",
            "with its own captured paragraph.",
        ]
    ) == [
        TextBlock("2020 - Present"),
        TextBlock("Responsibilities"),
        TextBlock("Built services", 0),
        TextBlock("using AWS and Go", 1),
        TextBlock("Next item", 0),
        TextBlock("Technologies"),
        TextBlock("Python"),
        TextBlock("A separate sentence,"),
        TextBlock("with its own captured paragraph."),
    ]


def test_inline_capture_preserves_unicode_spacing_but_not_html_comments() -> None:
    """
    Retain readable inline text across adjacent spans without copying non-visible HTML comments.

    Returns:
        None: Whitespace normalizes at presentation while words split only by markup remain intact.
    """
    parsed = parse_detail(
        "<main><div data-resume-entry><h3>Engineer</h3><p>Used&nbsp;Python "
        "<!-- capture diagnostic --><span>and <b>Go</b></span> for plat<span>form</span> work.</p></div></main>",
        "experience",
        "Experience",
    )
    assert text_blocks(parsed.entries[0].paragraphs) == [TextBlock("Used Python and Go for platform work.")]


@pytest.mark.parametrize(
    ("text", "heading"),
    [
        ("Projects", True),
        ("Technologies:", True),
        ("  Key Responsibilities  ", True),
        ("Practicing DevOps", False),
        ("Projects improved reliability.", False),
        ("Skills in Python", False),
    ],
)
def test_only_complete_subsection_labels_receive_heading_style(text: str, heading: bool) -> None:
    """
    Distinguish standalone body labels from complete sentences mentioning projects or skills.

    Args:
        text (str): Captured body text under consideration.
        heading (bool): Whether it introduces a job subsection.

    Returns:
        None: Heading recognition does not restyle ordinary prose.
    """
    assert is_body_heading(text) is heading


def test_reported_devops_projects_boundary_is_a_subheading(tmp_path: Path) -> None:
    """
    Make the actual subsection after the SBE Vision bullet visually distinct instead of joining it into the sentence.

    Args:
        tmp_path (Path): Isolated LaTeX output directory.

    Returns:
        None: The completed bullet, Projects heading, and following bullet remain separate semantic blocks.
    """
    paragraphs = [
        "SBE Vision, Inc.",
        "Aug 2022 - Feb 2024",
        "Responsibilities",
        "- Introduce new security, solutions and customs while practicing DevOps",
        "Projects",
        "- Introduced a scalable Kubernetes-based GitLab runners solution",
    ]
    entry = Entry("DevOps Engineer", paragraphs)
    profile = Profile("example-person", "Alex", sections=[Section("experience", "Experience", [entry])])
    source = render_profile(profile, Config(LinkedIn(profile.username)), tmp_path).read_text()
    bullet = r"\profilebullet{0}{Introduce new security, solutions and customs while practicing DevOps}"
    heading = r"\profilesubheading{Projects}"
    following = r"\profilebullet{0}{Introduced a scalable Kubernetes-based GitLab runners solution}"
    assert source.index(bullet) < source.index(heading) < source.index(following)
    assert r"\profileparagraph{Projects}" not in source
    assert entry.paragraphs == paragraphs


@pytest.mark.parametrize("highlight", [False, True])
@pytest.mark.parametrize("reflow", [False, True])
def test_configured_job_text_rules_apply_to_nested_roles(tmp_path: Path, highlight: bool, reflow: bool) -> None:
    """
    Load custom labels and independently control their emphasis and the reflow of nested role descriptions.

    Args:
        tmp_path (Path): Isolated config and LaTeX output directory.
        highlight (bool): Whether matched labels use subsection styling.
        reflow (bool): Whether captured continuation lines join their bullet.

    Returns:
        None: YAML rules reach grouped job rendering without changing source text or promoting partial label matches.
    """
    path = tmp_path / "resumeme.config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "linkedin": {"username": "example-person"},
                "experience": {"subheadings": ["Engineering outcomes"], "reflow_soft_breaks": reflow},
                "style": {"highlight_job_subheadings": highlight},
            }
        )
    )
    config = load_config(path)
    paragraphs = [
        "Jan 2024 - Present",
        "Responsibilities",
        "- Delivered services,\nengineering outcomes:\n- Built systems using\nAWS and Go.",
        "Engineering outcomes improved delivery.",
    ]
    role = Entry("Engineer", paragraphs)
    company = Entry("Example", [role.title, *role.paragraphs], positions=[role])
    profile = Profile("example-person", "Alex", sections=[Section("experience", "Experience", [company])])
    source = render_profile(profile, config, tmp_path).read_text().split(r"\begin{document}", 1)[1]
    command = "profilesubheading" if highlight else "profileparagraph"
    assert rf"\{command}{{engineering outcomes:}}" in source
    assert r"\profileparagraph{Responsibilities}" in source
    assert r"\profileparagraph{Engineering outcomes improved delivery.}" in source
    assert (r"\profilebullet{0}{Built systems using AWS and Go.}" in source) is reflow

    if not reflow:
        assert r"\profilebullet{0}{Built systems using}" in source
        assert r"\profileparagraph{AWS and Go.}" in source

    assert role.paragraphs == paragraphs


def test_defaults_and_empty_labels_keep_highlighting_separate_from_recognition(tmp_path: Path) -> None:
    """
    Enable subsection presentation by default while allowing an empty label list and theme-level opt-out.

    Args:
        tmp_path (Path): Isolated config and rendering directory.

    Returns:
        None: Defaults are discoverable; empty labels and a false theme override retain body text without emphasis.
    """
    assert Style().highlight_job_subheadings
    assert Experience().reflow_soft_breaks
    assert Experience().subheadings == list(BODY_HEADINGS)
    path = tmp_path / "resumeme.config.yaml"
    path.write_text(
        "linkedin:\n  username: example-person\nexperience:\n  subheadings: []\nstyle:\n"
        "  highlight_job_subheadings: true\n  theme: plain\n  themes:\n    plain:\n    "
        "  highlight_job_subheadings: false\n"
    )
    config = load_config(path)
    profile = Profile("example-person", "Alex", sections=[Section("experience", "Experience", [Entry("Engineer", ["Projects"])])])

    # Exercise the empty-list setting with highlighting enabled, then a theme override with default label recognition.
    for selected in (
        Config(config.linkedin, experience=config.experience),
        Config(config.linkedin, style=config.style),
    ):
        source = render_profile(profile, selected, tmp_path).read_text().split(r"\begin{document}", 1)[1]
        assert r"\profileparagraph{Projects}" in source
        assert r"\profilesubheading{Projects}" not in source


@pytest.mark.parametrize(
    "settings",
    [
        {"experience": {"reflow_soft_breaks": "false"}},
        {"experience": {"subheadings": "Projects"}},
        {"experience": {"subheadings": [""]}},
        {"experience": {"subheadings": ["   "]}},
        {"experience": {"subheadings": ["Projects\nSkills"]}},
        {"experience": {"subheadings": ["Projects", "Projects"]}},
        {"style": {"highlight_job_subheadings": "false"}},
        {"style": {"themes": {"plain": {"highlight_job_subheadings": "false"}}}},
    ],
)
def test_job_text_config_rejects_ambiguous_types(tmp_path: Path, settings: dict[str, object]) -> None:
    """
    Reject invalid toggles and malformed label lists before template rendering.

    Args:
        tmp_path (Path): Isolated configuration directory.
        settings (dict[str, object]): Invalid job text or style settings.

    Returns:
        None: The schema rejects malformed user input without coercion.
    """
    path = tmp_path / "resumeme.config.yaml"
    path.write_text(yaml.safe_dump({"linkedin": {"username": "example-person"}, **settings}))

    with pytest.raises(ValidationError):
        load_config(path)
