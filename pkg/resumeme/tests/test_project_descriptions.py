"""
Verify attachment descriptions move with project media without consuming neighboring role prose.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PIL import Image

from resumeme.compiler.asts.profile import Entry, Link, Media, Profile, Section
from resumeme.compiler.passes.project_descriptions import partition_descriptions
from resumeme.compiler.passes.projects import consolidate_projects
from resumeme.compiler.pipeline import render_profile
from resumeme.config import Config, LinkedIn

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("enabled", [True, False])
def test_shared_viewer_cards_move_each_description_and_respect_visibility(enabled: bool) -> None:
    """
    Keep descriptions with their own preview even when LinkedIn uses one viewer for several cards.

    Args:
        enabled (bool): Whether the consolidated Projects section is displayed.

    Returns:
        None: Role prose survives, card descriptions move or hide together, and the snapshot remains intact.
    """
    viewer = "https://www.linkedin.com/in/example/overlay/Position/123/treasury/"
    narrative = ["Example Co. · Full-time", "2024 - Present", "Built services and led the team."]
    images = [Media(f"https://example.org/{name}.png", alt=f"Thumbnail for {name}", link=viewer) for name in ("Website", "Store")]
    role = Entry(
        "Engineer",
        [*narrative, "Website", "Primary company website.", "Includes a blog.", "Store", "Manage store listings."],
        images=images,
    )
    profile = Profile("example-person", "Alex", sections=[Section("experience", "Experience", [role])])
    result, _ = consolidate_projects(profile, enabled=enabled)
    assert result.sections[0].entries[0].paragraphs == narrative
    assert result.sections[0].entries[0].images == []
    assert "Primary company website." in role.paragraphs and role.images == images

    if enabled:
        website, store = result.sections[1].entries
        assert website.paragraphs == ["Associated with Engineer at Example Co.", "Primary company website.", "Includes a blog."]
        assert store.paragraphs == ["Associated with Engineer at Example Co.", "Manage store listings."]
        assert website.images == [images[0]] and store.images == [images[1]]
    else:
        assert len(result.sections) == 1


def test_grouped_positions_rewrite_flattened_text_and_merge_descriptions_by_destination() -> None:
    """
    Remove attachment text from both representations of grouped employment while retaining role-specific context.

    Returns:
        None: Aliases merge into one project with both descriptions, and neither role loses its own narrative.
    """
    url = "https://github.com/example/tool"
    roles = [
        Entry("Staff", ["2024 - Present", "Led the team.", "Tool", "Added automation."], [Link("Tool", "https://lnkd.in/tool", url)]),
        Entry("Engineer", ["2020 - 2024", "Built services.", "Tool", "Created the first release."], [Link("Tool", url)]),
    ]
    group = Entry(
        "Example Co.",
        ["Full-time", *(line for role in roles for line in [role.title, *role.paragraphs])],
        [link for role in roles for link in role.links],
        positions=roles,
    )
    profile = Profile("example-person", "Alex", sections=[Section("experience", "Experience", [group])])
    result, _ = consolidate_projects(profile, enabled=True)
    company = result.sections[0].entries[0]
    assert company.paragraphs == ["Full-time", "Staff", "2024 - Present", "Led the team.", "Engineer", "2020 - 2024", "Built services."]
    assert [position.paragraphs for position in company.positions] == [
        ["2024 - Present", "Led the team."],
        ["2020 - 2024", "Built services."],
    ]
    assert len(result.sections[1].entries) == 1
    assert result.sections[1].entries[0].paragraphs == [
        "Associated with Staff at Example Co.",
        "Added automation.",
        "Associated with Engineer at Example Co.",
        "Created the first release.",
    ]
    assert "Added automation." in group.paragraphs


@pytest.mark.parametrize("boundary", [["Support Engineer", "2020 - 2024"], ["Responsibilities:"], ["Technologies"], ["Projects"]])
def test_attachment_description_stops_at_role_boundaries(boundary: list[str]) -> None:
    """
    Preserve later legacy roles and explicitly labeled role narrative after an attached card.

    Args:
        boundary (list[str]): Employment metadata or a role prose heading following the attachment.

    Returns:
        None: Only the attachment's adjacent description moves into the project.
    """
    role = Entry("Company", ["Built services.", "Tool", "Tool description.", *boundary, "Supported customers."])
    remaining, descriptions = partition_descriptions(role, {"tool": {"Tool"}})
    assert remaining == ["Built services.", *boundary, "Supported customers."]
    assert descriptions == {"tool": ["Tool description."]}


def test_ambiguous_captions_and_inline_mentions_do_not_claim_role_prose() -> None:
    """
    Require an unambiguous standalone caption instead of inferring ownership from a mention or repeated label.

    Returns:
        None: Both narrative forms remain in their original role when project ownership is uncertain.
    """
    role = Entry("Engineer", ["I built Tool for our team.", "Design", "Shared role narrative."])
    remaining, descriptions = partition_descriptions(role, {"first": {"Tool", "Design"}, "second": {"Design"}})
    assert remaining == role.paragraphs
    assert descriptions == {}


@pytest.mark.parametrize("illustrated", [True, False])
def test_project_description_follows_media_and_stays_out_of_experience(tmp_path: Path, illustrated: bool) -> None:
    """
    Render consolidated descriptions below their media, with affiliations above and text-only cards still readable.

    Args:
        tmp_path (Path): Isolated rendering and asset directory.
        illustrated (bool): Whether the project has a captured illustration.

    Returns:
        None: The project description appears once in Projects after its image and preserves inline links.
    """
    Image.new("RGB", (100, 60), "blue").save(tmp_path / "preview.png")
    url = "https://example.org/tool"
    description = f"Read {url} for the architecture."
    preview = Media("https://example.org/preview.png", alt="Thumbnail for Tool", path="preview.png", link=url)
    role = Entry("Engineer", ["Built the platform.", "Tool", description], [Link("Tool", url)], [preview] if illustrated else [])
    profile = Profile("example-person", "Alex", sections=[Section("experience", "Experience", [role])])
    source = render_profile(profile, Config(LinkedIn(profile.username)), tmp_path).read_text()
    experience, projects = source.split(r"\projectrow[", 1)
    assert "Built the platform." in experience
    assert "for the architecture." not in experience
    assert projects.count("for the architecture.") == 1
    assert rf"Read \href{{{url}}}{{{url}}} for the architecture." in projects.replace(r"\allowbreak{}", "")

    association = r"Associated with \hyperlink{resumeme-section-0-job-0}{Engineer}"

    if illustrated:
        assert projects.index(association) < projects.index(r"\includegraphics[") < projects.index("for the architecture.")
    else:
        assert projects.index(association) < projects.index("for the architecture.")


def test_featured_post_keeps_its_own_text_when_a_preview_moves() -> None:
    """
    Keep Featured narration in the post while only employment attachment descriptions move with their cards.

    Returns:
        None: The Featured post retains every original paragraph after its external reference moves.
    """
    post = Entry("Update", ["Tool", "What I learned building this."], [Link("Tool", "https://example.org/tool")])
    profile = Profile("example-person", "Alex", sections=[Section("featured", "Featured", [post])])
    result, _ = consolidate_projects(profile, enabled=True)
    assert result.sections[0].entries[0].paragraphs == post.paragraphs
    assert result.sections[1].entries[0].paragraphs == ["Featured project"]
