"""
Verify configurable section order, navigation, and shared Featured/Projects tiles.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml
from jsonschema import ValidationError

from resumeme.compiler.asts.profile import Entry, Link, Profile, Section, Skill
from resumeme.compiler.constants.sections import DEFAULT_SECTION_ORDER, SECTION_TITLES
from resumeme.compiler.passes.ordering import order_sections
from resumeme.compiler.pipeline import render_profile
from resumeme.config import Config, LinkedIn, load_config


def test_default_order_matches_config_schema_and_section_catalog(tmp_path: Path) -> None:
    """
    Cover the complete section catalog without constraining an adopter's edited configuration.

    Args:
        tmp_path (Path): Minimal fork configuration directory.

    Returns:
        None: Package and schema defaults agree, with no shared mutable lists.
    """
    path = tmp_path / "resumeme.config.yaml"
    path.write_text("linkedin:\n  username: example-person\n")
    config = load_config(path)
    root = Path(__file__).resolve().parents[3]
    schema = json.loads((root / "pkg/resumeme/compiler/asts/resources/config.schema.json").read_text())
    assert config.section_order == schema["properties"]["section_order"]["default"]
    assert tuple(config.section_order) == DEFAULT_SECTION_ORDER
    assert len(config.section_order) == len(set(config.section_order)) == len(SECTION_TITLES)
    config.section_order.clear()
    assert Config(LinkedIn("example-person")).section_order == list(DEFAULT_SECTION_ORDER)


@pytest.mark.parametrize("order", ["about,featured", ["about", "about"], ["bad key"], [3]])
def test_section_order_rejects_invalid_values(tmp_path: Path, order: object) -> None:
    """
    Reject malformed arrays and repeated literal keys before rendering.

    Args:
        tmp_path (Path): Temporary configuration directory.
        order (object): Invalid order value.

    Returns:
        None: Strict schema validation rejects ambiguous input.
    """
    path = tmp_path / "resumeme.config.yaml"
    path.write_text(yaml.safe_dump({"linkedin": {"username": "example-person"}, "section_order": order}))

    with pytest.raises(ValidationError):
        load_config(path)


def test_order_selects_only_listed_sections_and_resolves_aliases() -> None:
    """
    Resolve aliases while allowing explicitly listed unfamiliar sections and stable repeated observations.

    Returns:
        None: Omitted keys are hidden, an empty order hides everything, and the source remains intact.
    """
    sections = [Section(key, key) for key in ("custom", "about", "custom", "education", "certifications")]
    result = order_sections(sections, ["licenses-certifications", "education", "missing", "certifications"])
    assert result == [sections[4], sections[3]]
    assert order_sections(sections, ["custom"]) == [sections[0], sections[2]]
    assert order_sections(sections, []) == []
    assert [section.key for section in sections] == ["custom", "about", "custom", "education", "certifications"]


@pytest.mark.parametrize("contact_first", [False, True])
def test_configured_order_controls_body_contents_and_generated_sections(tmp_path: Path, contact_first: bool) -> None:
    """
    Honor ordering after visibility and synthesis, including Contact placement and internal role links.

    Args:
        tmp_path (Path): Isolated rendering directory.
        contact_first (bool): Whether Contact leads the requested sequence in the identity column.

    Returns:
        None: Body headings and contents agree, with every generated destination present exactly once.
    """
    role = Entry("Engineer", ["Example", "2022 - Present"], [Link("Tool", "https://example.org/tool")], skills=[Skill("Python", 2)])
    profile = Profile(
        "example-person",
        "Alex",
        sections=[
            Section("about", "About", [Entry("Complete narrative")]),
            Section("experience", "Experience", [role]),
            Section("contact", "Contact info", [Entry("Website")]),
            Section("education", "Education", [Entry("Hidden school")]),
            Section("patents", "Patents"),
            Section("custom", "Custom", [Entry("Extra content")]),
        ],
    )
    order = ["projects", "skills", "experience", "contact", "about", "patents", "custom"]

    if contact_first:
        order.remove("contact")
        order.insert(0, "contact")

    config = Config(LinkedIn(profile.username), section_order=order, project_filter=None)
    text = render_profile(profile, config, tmp_path).read_text().split(r"\begin{document}", 1)[1]
    titles = ["Projects", "Skills", "Experience", "Contact info", "About", "Custom"]

    if contact_first:
        titles.remove("Contact info")
        titles.insert(0, "Contact info")

    assert re.findall(r"\\sectiontitle\{([^}]+)\}", text) == titles
    assert re.findall(r"\\hyperlink\{resumeme-section-\d+\}\{([^}]+)\}", text) == titles
    assert (text.index(r"\sectiontitle{Contact info}") < text.index(r"\framebreak")) is contact_first
    anchors = re.findall(r"\\hypertarget\{([^}]+)\}", text)
    assert len(anchors) == len(set(anchors))
    assert all(target in anchors for target in re.findall(r"\\hyperlink\{([^}]+)\}", text))
    assert "Hidden school" not in text and r"\sectiontitle{Patents}" not in text

    # Custom templates consume the same order rather than accidentally reverting to capture order.
    template = tmp_path / "ordered.j2"
    template.write_text("((* for section in profile.sections *))((( section.title )))|((* endfor *))")
    custom = Config(LinkedIn(profile.username), section_order=order, template=template.name, project_filter=None)
    assert render_profile(profile, custom, tmp_path).read_text() == "|".join(titles) + "|"


@pytest.mark.parametrize("disabled", [False, True])
def test_featured_uses_project_tiles_without_enabling_hidden_posts(tmp_path: Path, disabled: bool) -> None:
    """
    Tile Featured entries in pairs while preserving complete prose and respecting exclusions.

    Args:
        tmp_path (Path): Temporary rendering directory.
        disabled (bool): Whether Featured is explicitly hidden.

    Returns:
        None: Visible posts share the Projects tile renderer, including an odd final entry.
    """
    posts = [Entry(f"Post {index}", [f"Complete post {index} & its context."]) for index in range(3)]
    profile = Profile(
        "example-person", "Alex", sections=[Section("featured", "Featured", posts), Section("projects", "Projects", [Entry("Tool")])]
    )
    config = Config(LinkedIn(profile.username), section_order=["projects"] if disabled else ["featured", "projects"], project_filter=None)
    text = render_profile(profile, config, tmp_path).read_text().split(r"\begin{document}", 1)[1]
    assert text.count(r"\projectrow[") == (1 if disabled else 3)
    assert (r"\sectiontitle{Featured}" in text) is not disabled

    for index in range(3):
        assert (rf"Complete post {index} \& its context." in text) is not disabled

    assert profile.sections[0].entries == posts


@pytest.mark.parametrize("commented", [False, True])
def test_commenting_out_a_section_disables_it(tmp_path: Path, commented: bool) -> None:
    """
    Use the actual YAML editing workflow to enable, order, and hide a captured section.

    Args:
        tmp_path (Path): Temporary fork configuration directory.
        commented (bool): Whether the user comments out the Featured entry.

    Returns:
        None: Commented entries contribute no headings, tiles, or contents links.
    """
    path = tmp_path / "resumeme.config.yaml"
    marker = "# " if commented else ""
    path.write_text(f"linkedin:\n  username: example-person\nsection_order:\n  {marker}- featured\n  - about\n")
    config = load_config(path)
    profile = Profile(
        "example-person", "Alex", sections=[Section("about", "About", [Entry("Intro")]), Section("featured", "Featured", [Entry("Post")])]
    )
    document = render_profile(profile, config, tmp_path).read_text().split(r"\begin{document}", 1)[1]
    assert re.findall(r"\\sectiontitle\{([^}]+)\}", document) == (["About"] if commented else ["Featured", "About"])


def test_removed_disable_field_is_rejected(tmp_path: Path) -> None:
    """
    Require a single visibility source rather than silently retaining conflicting settings.

    Args:
        tmp_path (Path): Temporary configuration directory.

    Returns:
        None: Legacy top-level disable is rejected by the strict schema.
    """
    path = tmp_path / "resumeme.config.yaml"
    path.write_text("linkedin:\n  username: example-person\ndisable: [featured]\n")

    with pytest.raises(ValidationError, match="disable"):
        load_config(path)
