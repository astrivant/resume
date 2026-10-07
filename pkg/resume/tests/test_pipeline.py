"""
Exercise profile preservation, configuration boundaries, and safe rendering.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from attrs import evolve
from jsonschema import ValidationError
from PIL import Image

from resume.cli import main
from resume.config import Config, LinkedIn, load_config, project_path
from resume.latex.escaping import latex_escape
from resume.latex.rendering import render_profile
from resume.linkedin.parsing import detail_links, merge_profile_html, parse_contact, parse_detail, parse_profile, safe_url
from resume.models import Entry, Link, Media, Profile, Section, load_profile, save_profile


@pytest.fixture
def html() -> str:
    """
    Read the synthetic profile fixture used to verify LinkedIn markup handling.

    Returns:
        str: Profile HTML without personal account data.
    """
    return Path(__file__).with_name("fixtures").joinpath("profile.html").read_text(encoding="utf-8")


def test_profile_keeps_grouped_jobs_and_project_links(html: str) -> None:
    """
    Preserve nested positions, full descriptions, images, and original destinations.

    Args:
        html (str): Synthetic profile page.

    Returns:
        None: Assertions establish complete extraction from supported markup.
    """
    profile = parse_profile(html, "example-person")
    assert profile.name == "Alex Example"
    assert [section.key for section in profile.sections] == ["about", "experience", "projects"]
    experience = profile.sections[1].entries
    assert len(experience) == 1
    assert experience[0].title == "Example Systems"
    assert "Staff Engineer" in experience[0].paragraphs
    assert "Senior Engineer" in experience[0].paragraphs
    assert "Built the first release." in experience[0].paragraphs
    assert len(experience[0].images) == 2
    assert experience[0].links[-1].url == "https://example.org/project?a=1&b=2#architecture"
    assert "visually-hidden" not in json.dumps(profile.intro)
    assert "Edit profile" not in profile.intro


def test_detail_routes_stay_with_owner(html: str) -> None:
    """
    Follow only the configured owner's section pages.

    Args:
        html (str): Profile containing both owned and unrelated detail links.

    Returns:
        None: Route discovery excludes other profiles.
    """
    assert detail_links(html, "example-person") == {"experience": "https://www.linkedin.com/in/example-person/details/experience/"}


def test_new_profile_layout_uses_h2_and_excludes_sidebar() -> None:
    """
    Support the current LinkedIn primary-content layout without parsing sidebar cards.

    Returns:
        None: New semantic headings and content boundaries produce an owner profile.
    """
    html = """<main><section aria-label="Primary content">
        <section componentkey="intro"><h2>Alex Example</h2><p>Engineer</p></section>
        <section componentkey="about"><h2>About</h2><p>Complete profile text.</p></section>
        </section><section><h2>People you may know</h2><p>Unrelated person</p></section></main>"""
    profile = parse_profile(html, "example-person")
    assert profile.name == "Alex Example"
    assert [section.title for section in profile.sections] == ["About"]


def test_unknown_sections_and_long_text_are_retained() -> None:
    """
    Preserve unfamiliar section names and descriptions without arbitrary truncation.

    Returns:
        None: Entire long-form profile text survives parsing.
    """
    text = "Complete research narrative. " * 1000
    html = f"<main><section><h1>Example</h1></section><section><h2>Independent studies</h2><p>{text}</p></section></main>"
    profile = parse_profile(html, "example-person")
    assert profile.sections[0].key == "independent-studies"
    assert profile.sections[0].entries[0].title == text.strip()


@pytest.mark.parametrize("html", ["<form>Sign in</form>", "<main><h1>Sign in</h1><input type='password'></main>"])
def test_unsupported_pages_fail_instead_of_saving_empty_profile(html: str) -> None:
    """
    Reject login screens while allowing profile pages with no optional sections.

    Args:
        html (str): Incomplete or unrelated HTML.

    Returns:
        None: Parsing fails visibly.
    """

    with pytest.raises(ValueError):
        parse_profile(html, "example-person")


def test_detail_page_rejects_empty_lists() -> None:
    """
    Avoid replacing an existing profile preview with an empty detail page.

    Returns:
        None: Missing detail content produces an actionable error.
    """

    with pytest.raises(ValueError, match="No detail entries"):
        parse_detail("<main><h2>Experience</h2></main>", "experience", "Experience")


def test_virtualized_profile_preserves_earlier_cards() -> None:
    """
    Keep identity and upper cards after scrolling removes them from the live DOM.

    Returns:
        None: Merged snapshots preserve every observed card in profile order.
    """
    snapshots = [
        '<main><section aria-label="Primary content"><section><h2>Alex Example</h2><p>Engineer</p></section>'
        "<section><h2>About</h2><p>First card</p></section></section></main>",
        '<main><section aria-label="Primary content"><section><h2>About</h2><p>Fully expanded first card</p></section>'
        "<section><h2>Projects 5</h2><p>Final card</p></section></section></main>",
    ]
    profile = parse_profile(merge_profile_html(snapshots), "example-person")
    assert profile.name == "Alex Example"
    assert [section.title for section in profile.sections] == ["About", "Projects"]
    assert profile.sections[0].entries[0].title == "Fully expanded first card"


@pytest.mark.parametrize("component", ["entity-collection-item--job", "entity-collection-item-job", "3ab56c5a-dccf-4f5a-a18f-3b0bcb086b32"])
def test_detail_entries_keep_titles_above_nested_bullet_lists(component: str) -> None:
    """
    Preserve the whole job record when its description contains an HTML list.

    Args:
        component (str): Stable or generated identifier used by LinkedIn's detail layout.

    Returns:
        None: Job identity, duties, and logo remain associated in a single entry.
    """
    html = f'<main><p>Experience</p><div componentkey="{component}">'
    html += "<p>Staff Engineer</p><p>Example Company</p><ul><li>Designed systems</li><li>Mentored colleagues</li></ul>"
    html += '<img src="https://example.org/logo.png"></div></main>'
    entries = parse_detail(html, "experience", "Experience").entries
    assert len(entries) == 1
    assert entries[0].title == "Staff Engineer"
    assert entries[0].paragraphs == ["Example Company", "Designed systems", "Mentored colleagues"]
    assert entries[0].images[0].url == "https://example.org/logo.png"


def test_emoji_rendering_preserves_sequences_and_escapes_surrounding_text() -> None:
    """
    Translate profile emoji to bundled graphics without exposing neighboring TeX syntax.

    Returns:
        None: Emoji sequences remain intact while ordinary text is escaped.
    """
    assert latex_escape("Plants 🪴 & engineering 👩‍💻") == r"Plants \texttwemoji{1fab4} \& engineering \texttwemoji{1f469-200d-1f4bb}"


def test_contact_dialog_retains_fields_without_unrelated_page_content() -> None:
    """
    Capture the owner's contact overlay while excluding advertisements and edit controls.

    Returns:
        None: Only the requested contact fields appear in the section.
    """
    html = "<main><p>Unrelated sidebar</p></main><dialog open><h2>Contact info</h2>"
    html += '<div data-testid="dialog-content"><p>Email</p><p>alex@example.org</p>'
    html += '<a href="https://example.org">Website</a><button>Edit</button>'
    html += '<div componentkey="auto-component-promotion"><p>Unrelated promotion</p>'
    html += '<img src="https://example.org/ad.png"><a href="https://www.linkedin.com/premium/products/">Upgrade</a></div></div></dialog>'
    contact = parse_contact(html)
    assert contact.entries[0].title == "Email"
    assert contact.entries[0].paragraphs == ["alex@example.org", "Website"]
    assert contact.entries[0].links == [Link("Website", "https://example.org")]
    assert not contact.entries[0].images


def test_experience_omits_attached_skills_but_keeps_job_description() -> None:
    """
    Remove LinkedIn skill summaries only from jobs while preserving ordinary technical descriptions.

    Returns:
        None: Experience omits attached skill tags; projects and the main Skills section retain theirs.
    """
    html = '<main><div componentkey="entity-collection-item-job"><p>Engineer</p><p>Built Python services.</p>'
    html += '<a href="/in/example-person/overlay/123/skill-associations-details/?associationType=position">'
    html += "Python, Leadership and +3 skills</a></div></main>"
    job = parse_detail(html, "experience", "Experience").entries[0]
    assert job.title == "Engineer"
    assert job.paragraphs == ["Built Python services."]
    project = parse_detail(html, "projects", "Projects").entries[0]
    assert project.paragraphs == ["Built Python services.", "Python, Leadership and +3 skills"]


@pytest.mark.parametrize(
    "url", ["javascript:alert(1)", "file:///etc/passwd", "https://user:password@example.org", "#edit", "https://x/{x}"]
)
def test_unsafe_links_are_rejected(url: str) -> None:
    """
    Restrict rendered destinations to credential-free web URLs.

    Args:
        url (str): Unsupported destination.

    Returns:
        None: The unsafe reference is dropped.
    """
    assert safe_url(url) == ""


def test_config_defaults_and_unknown_fields(tmp_path: Path) -> None:
    """
    Support username-only configuration and reject misspelled options.

    Args:
        tmp_path (Path): Temporary project directory.

    Returns:
        None: Defaults work and unknown options fail schema validation.
    """
    path = tmp_path / "resume.config.yaml"
    path.write_text("linkedin:\n  username: example-person\n", encoding="utf-8")
    config = load_config(path)
    assert config.output.pdf == "resume.pdf"
    assert config.disable == []
    assert config.style.show_header_photo is True
    assert config.style.paper == "letter"
    assert config.style.background == "FFFFFF"
    path.write_text("linkedin:\n  username: example-person\n  password: forbidden\n", encoding="utf-8")

    with pytest.raises(ValidationError):
        load_config(path)


@pytest.mark.parametrize("disabled", [[], ["about"], ["contact"], ["about", "contact", "projects"]])
def test_opening_columns_respect_section_visibility(tmp_path: Path, disabled: list[str]) -> None:
    """
    Place contact details before the column break and About first in the body after filtering.

    Args:
        tmp_path (Path): Isolated render destination.
        disabled (list[str]): Section keys excluded by the user.

    Returns:
        None: Enabled content appears once in its intended column, with no empty body forced for a minimal profile.
    """
    path = tmp_path / "resume.config.yaml"
    path.write_text("linkedin:\n  username: example-person\n", encoding="utf-8")
    config = evolve(load_config(path), disable=disabled)

    # Capture order is deliberately different from presentation order; filtering still owns what reaches either column.
    profile = Profile(
        "example-person",
        "Alex Example",
        sections=[
            Section("projects", "Projects", [Entry("Project example")]),
            Section("contact", "Contact", [Entry("Contact example")]),
            Section("about", "About", [Entry("About example")]),
        ],
    )
    rendered = render_profile(profile, config, tmp_path).read_text(encoding="utf-8").split(r"\begin{document}", 1)[1]

    for key in ("about", "contact", "projects"):
        assert (f"\\sectiontitle{{{key.title()}}}" in rendered) == (key not in disabled)

    if "projects" in disabled:
        assert "\\framebreak" not in rendered
        return

    before, after = rendered.split("\\framebreak", 1)
    assert ("Contact example" in before) == ("contact" not in disabled)
    assert "Contact example" not in after
    assert "Project example" in after

    if "about" not in disabled:
        assert after.index("About example") < after.index("Project example")


@pytest.mark.parametrize("value", ["skills", "[skills, skills]", "[null]", "[Skills]", "['']"])
def test_disable_rejects_invalid_section_lists(tmp_path: Path, value: str) -> None:
    """
    Reject malformed section exclusions before rendering.

    Args:
        tmp_path (Path): Temporary project directory.
        value (str): Invalid YAML value for the disable field.

    Returns:
        None: Invalid types, duplicate keys, and malformed section names fail validation.
    """
    config = tmp_path / "resume.config.yaml"
    config.write_text(f"linkedin:\n  username: example-person\ndisable: {value}\n", encoding="utf-8")

    with pytest.raises(ValidationError):
        load_config(config)


@pytest.mark.parametrize("custom_template", [False, True])
def test_disabled_sections_are_omitted_without_changing_capture(tmp_path: Path, custom_template: bool) -> None:
    """
    Exclude complete sections before asset staging and template rendering without changing saved inputs.

    Args:
        tmp_path (Path): Temporary project directory.
        custom_template (bool): Whether to exercise a user-supplied template.

    Returns:
        None: Excluded content and media disappear from output while the snapshot stays intact.
    """
    config = tmp_path / "resume.config.yaml"
    config.write_text("linkedin:\n  username: example-person\ndisable: [skills, independent-studies]\n", encoding="utf-8")

    if custom_template:
        with config.open("a", encoding="utf-8") as stream:
            stream.write("template: custom.tex.j2\n")

        (tmp_path / "custom.tex.j2").write_text("((( profile )))", encoding="utf-8")

    Image.new("RGB", (20, 20), "blue").save(tmp_path / "hidden.png")
    profile = Profile(
        "example-person",
        "Alex Example",
        sections=[
            Section("about", "About", [Entry("Visible narrative")]),
            Section(
                "skills",
                "Skills",
                [Entry("Hidden skill", ["Hidden description"], [Link("Hidden link", "https://example.org/hidden")])],
            ),
            Section(
                "independent-studies",
                "Independent studies",
                [
                    Entry(
                        "Hidden research",
                        images=[Media("https://example.org/hidden.png", path="hidden.png"), Media("https://example.org/missing")],
                    )
                ],
            ),
        ],
    )
    snapshot = tmp_path / "data/profile.json"
    save_profile(profile, snapshot)
    original = snapshot.read_bytes()
    assert main(["--config", str(config), "render"]) == 0
    rendered = (tmp_path / "tex/resume.tex").read_text(encoding="utf-8")
    assert "Visible narrative" in rendered

    for hidden in ["Skills", "Independent studies", "Hidden", "https://example.org/hidden", "hidden.png"]:
        assert hidden not in rendered

    assert not list((tmp_path / "tex/assets").iterdir())
    assert snapshot.read_bytes() == original
    assert load_profile(snapshot, "example-person") == profile

    # Re-enabling the sections restores the requirement to resolve their missing images.
    with pytest.raises(ValueError, match="not downloaded"):
        render_profile(profile, evolve(load_config(config), disable=[]), tmp_path)


def test_disabling_every_section_keeps_the_profile_header(tmp_path: Path) -> None:
    """
    Allow a header-only resume and tolerate exclusions absent from this snapshot.

    Args:
        tmp_path (Path): Temporary project directory.

    Returns:
        None: The owner's header remains and all excluded section headings are absent.
    """
    profile = Profile("example-person", "Alex Example", sections=[Section("about", "About", [Entry("Hidden narrative")])])
    config = Config(LinkedIn("example-person"), disable=["about", "interests"])
    rendered = render_profile(profile, config, tmp_path).read_text(encoding="utf-8")
    assert "Alex Example" in rendered
    assert r"\sectiontitle{About}" not in rendered
    assert "Hidden narrative" not in rendered


@pytest.mark.parametrize("show_header_photo", [False, True])
@pytest.mark.parametrize("custom_template", [False, True])
def test_header_photo_visibility_preserves_other_images_and_snapshot(
    tmp_path: Path, show_header_photo: bool, custom_template: bool
) -> None:
    """
    Toggle cover photos without hiding portraits or section media or modifying captured data.

    Args:
        tmp_path (Path): Temporary project directory.
        show_header_photo (bool): Whether cover photos should be rendered and staged.
        custom_template (bool): Whether to inspect the complete input to a custom template.

    Returns:
        None: Only enabled photos reach templates and staged assets; the saved snapshot stays intact.
    """
    config_path = tmp_path / "resume.config.yaml"
    config_path.write_text(
        f"linkedin:\n  username: example-person\nstyle:\n  show_header_photo: {str(show_header_photo).lower()}\n",
        encoding="utf-8",
    )
    config = load_config(config_path)

    if custom_template:
        (tmp_path / "custom.tex.j2").write_text("((( profile )))", encoding="utf-8")
        config = evolve(config, template="custom.tex.j2")

    for name, color in [("cover", "red"), ("portrait", "blue"), ("logo", "green")]:
        Image.new("RGB", (20, 20), color).save(tmp_path / f"{name}.png")

    profile = Profile(
        "example-person",
        "Alex Example",
        images=[
            Media("https://example.org/cover.png", alt="Cover photo", path="cover.png"),
            Media("https://example.org/background.png", alt="BACKGROUND photo", path="cover.png"),
            Media("https://media.licdn.com/dms/image/v2/example/profile-displaybackgroundimage-shrink_200_800", path="cover.png"),
            Media("https://example.org/portrait.png", alt="Alex Example", path="portrait.png"),
        ],
        sections=[
            Section("experience", "Experience", [Entry("Engineer", images=[Media("https://example.org/logo.png", path="logo.png")])])
        ],
    )
    snapshot = tmp_path / "data/profile.json"
    save_profile(profile, snapshot)
    original = snapshot.read_bytes()
    source = render_profile(profile, config, tmp_path)
    rendered = source.read_text(encoding="utf-8")
    expected_assets = set()

    for name in ["cover", "portrait", "logo"]:
        data = (tmp_path / f"{name}.png").read_bytes()
        asset = hashlib.sha256(data).hexdigest() + ".png"
        visible = name != "cover" or show_header_photo
        assert (f"assets/{asset}" in rendered) == visible

        if visible:
            expected_assets.add(asset)

    assert {asset.name for asset in (source.parent / "assets").iterdir()} == expected_assets

    if not custom_template:
        assert rendered.count(r"\includegraphics[width=\linewidth]") == (3 if show_header_photo else 0)

    assert "Alex Example" in rendered
    assert "Engineer" in rendered
    assert snapshot.read_bytes() == original
    assert load_profile(snapshot, "example-person") == profile


@pytest.mark.parametrize("value", ['"false"', "0", "null"])
def test_header_photo_visibility_rejects_non_boolean_values(tmp_path: Path, value: str) -> None:
    """
    Reject values that could otherwise silently coerce to the wrong visibility setting.

    Args:
        tmp_path (Path): Temporary project directory.
        value (str): Non-boolean YAML value.

    Returns:
        None: Schema validation rejects the invalid switch.
    """
    config = tmp_path / "resume.config.yaml"
    config.write_text(f"linkedin:\n  username: example-person\nstyle:\n  show_header_photo: {value}\n", encoding="utf-8")

    with pytest.raises(ValidationError):
        load_config(config)


def test_hidden_header_photo_does_not_require_a_download(tmp_path: Path) -> None:
    """
    Skip missing cover assets only when their display has been explicitly disabled.

    Args:
        tmp_path (Path): Temporary project directory.

    Returns:
        None: Hiding the photo permits rendering; showing it requires the captured asset.
    """
    profile = Profile("example-person", "Alex Example", images=[Media("https://example.org/cover.png", alt="Cover photo")])
    config = Config(LinkedIn("example-person"))
    hidden = evolve(config, style=evolve(config.style, show_header_photo=False))
    assert render_profile(profile, hidden, tmp_path).exists()

    with pytest.raises(ValueError, match="not downloaded"):
        render_profile(profile, config, tmp_path)


def test_paths_reject_parent_traversal_and_symlinks(tmp_path: Path) -> None:
    """
    Keep generated files inside the configured project boundary.

    Args:
        tmp_path (Path): Temporary project directory.

    Returns:
        None: Direct and symlink-mediated escapes are rejected.
    """

    with pytest.raises(ValueError):
        project_path(tmp_path, "../outside.pdf")

    (tmp_path / "outside").symlink_to(tmp_path.parent, target_is_directory=True)

    with pytest.raises(ValueError):
        project_path(tmp_path, "outside/unrelated.pdf")


def test_snapshot_roundtrip_and_owner_binding(tmp_path: Path, html: str) -> None:
    """
    Keep portable data intact while refusing to render a previous fork owner's data.

    Args:
        tmp_path (Path): Temporary project directory.
        html (str): Synthetic profile page.

    Returns:
        None: Roundtrip preserves data and mismatched ownership fails.
    """
    profile = parse_profile(html, "example-person")
    path = tmp_path / "data/profile.json"
    save_profile(profile, path)
    assert load_profile(path, "example-person") == profile

    with pytest.raises(ValueError, match="Snapshot username"):
        load_profile(path, "someone-else")


def test_tex_injection_is_literal_text(tmp_path: Path) -> None:
    """
    Preserve hostile-looking display text without creating executable TeX commands.

    Args:
        tmp_path (Path): Temporary project directory.

    Returns:
        None: TeX syntax from profile text is fully escaped.
    """
    attack = r"100% R&D_#1 $value \input{/etc/passwd} ~ ^"
    profile = Profile("example-person", "Alex Example", sections=[Section("about", "About", [Entry(attack)])])
    source = render_profile(profile, Config(LinkedIn("example-person")), tmp_path).read_text(encoding="utf-8")
    assert r"\input{/etc/passwd}" not in source
    assert latex_escape(attack) in source


def test_render_requires_explicit_acceptance_of_missing_images(tmp_path: Path) -> None:
    """
    Refuse an apparently complete PDF when image downloads are missing.

    Args:
        tmp_path (Path): Temporary project directory.

    Returns:
        None: Missing imagery cannot disappear without explicit acceptance.
    """
    profile = Profile("example-person", "Alex Example", images=[Media("https://example.org/missing.png")])
    config = Config(LinkedIn("example-person"))

    with pytest.raises(ValueError, match="not downloaded"):
        render_profile(profile, config, tmp_path)

    assert render_profile(profile, config, tmp_path, allow_incomplete=True).exists()


def test_render_copies_only_referenced_images(tmp_path: Path) -> None:
    """
    Make generated TeX portable without copying unrelated profile or credential files.

    Args:
        tmp_path (Path): Temporary project directory.

    Returns:
        None: A single referenced PNG is staged beside the source.
    """
    Image.new("RGB", (20, 20), "blue").save(tmp_path / "logo.png")
    (tmp_path / "unrelated.txt").write_text("unrelated", encoding="utf-8")
    profile = Profile("example-person", "Alex Example", images=[Media("https://example.org/logo.png", path="logo.png")])
    source = render_profile(profile, Config(LinkedIn("example-person")), tmp_path)
    assets = list((source.parent / "assets").iterdir())
    assert len(assets) == 1
    assert assets[0].read_bytes() == (tmp_path / "logo.png").read_bytes()


def test_capture_warnings_stop_validation(tmp_path: Path) -> None:
    """
    Report incomplete captures through the CLI's failure status.

    Args:
        tmp_path (Path): Temporary project directory.

    Returns:
        None: Warning-bearing snapshots require explicit acceptance.
    """
    config = tmp_path / "resume.config.yaml"
    config.write_text("linkedin:\n  username: example-person\n", encoding="utf-8")
    profile = Profile("example-person", "Alex Example", warnings=["Some text could not be expanded."])
    save_profile(profile, tmp_path / "data/profile.json")
    assert main(["--config", str(config), "validate"]) == 2
    assert main(["--config", str(config), "validate", "--allow-incomplete"]) == 0
    save_profile(evolve(profile, warnings=[]), tmp_path / "data/profile.json")
    assert main(["--config", str(config), "render"]) == 0
