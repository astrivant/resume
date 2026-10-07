"""
Verify optional connection metadata and concise first-page identity rendering.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml
from attrs import evolve
from jsonschema import ValidationError
from PIL import Image

from resumeme.compiler.asts.parsing import parse_profile
from resumeme.compiler.asts.profile import Entry, Link, Media, Profile, Section
from resumeme.compiler.constants.sections import DEFAULT_SECTION_ORDER
from resumeme.compiler.passes.header import prepare_header, prepare_header_logos
from resumeme.compiler.pipeline import render_profile
from resumeme.config import Config, GitHub, LinkedIn, Style, load_config

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("show", [False, True])
@pytest.mark.parametrize("explicit", [False, True])
def test_headline_visibility_preserves_company_location_and_source(show: bool, explicit: bool) -> None:
    """
    Hide only an identified headline, including legacy role-at-company text, and preserve the source for re-enabling.

    Args:
        show (bool): Effective headline visibility.
        explicit (bool): Whether capture supplied a structured headline field.

    Returns:
        None: Company and location survive either setting and the saved profile stays intact.
    """
    headline = "Building useful systems" if explicit else "Owner @ Example"
    intro = ["She/Her", headline, "Example Co.", "Boston, MA"]
    profile = Profile("example-person", "Alex", intro=intro, headline=headline if explicit else "")
    visible, _, _ = prepare_header(profile, Style(show_headline=show))
    assert (headline in visible.intro) is show
    assert visible.intro[-2:] == ["Example Co.", "Boston, MA"]
    assert visible.intro[0] == "She/Her"
    assert profile.intro == intro


@pytest.mark.parametrize("intro", [[], ["Boston, MA"], ["Example Co.", "Boston, MA"]])
def test_missing_headline_does_not_remove_minimal_identity(intro: list[str]) -> None:
    """
    Preserve header fields when no headline can be identified.

    Args:
        intro (list[str]): Minimal captured identity without a headline.

    Returns:
        None: Default visibility does not guess that the first company or location is a headline.
    """
    profile = Profile("example-person", "Alex", intro=intro)
    assert prepare_header(profile, Style())[0].intro == intro


@pytest.mark.parametrize("username", [None, "emmeowzing"])
def test_social_links_follow_identity_with_platform_icons(tmp_path: Path, username: str | None) -> None:
    """
    Render the optional GitHub profile directly after LinkedIn with icons to each link's left.

    Args:
        tmp_path (Path): Isolated rendering directory.
        username (str | None): Public GitHub account or an omitted link.

    Returns:
        None: Header order and URLs follow configuration without retaining the hidden headline.
    """
    profile = Profile("example-person", "Alex", intro=["Owner @ Example", "Example Co.", "Boston, MA"])
    config = Config(LinkedIn(profile.username), github=GitHub(username))
    source = render_profile(profile, config, tmp_path).read_text().split(r"\begin{document}", 1)[1]
    assert "Owner @ Example" not in source
    assert source.index("Example Co.") < source.index("Boston, MA") < source.index(r"\faLinkedin")
    assert (r"\faGithub" in source) is bool(username)

    if username:
        assert source.index(r"\faLinkedin") < source.index(r"\faGithub")
        assert rf"\href{{https://github.com/{username}}}" in source
        assert f"GitHub: {username}" in source


def test_headline_theme_and_github_config_validation(tmp_path: Path) -> None:
    """
    Validate optional social identity and apply headline visibility through normal theme precedence.

    Args:
        tmp_path (Path): Isolated config and template directory.

    Returns:
        None: The default hides headlines, theme overrides restore them, and unsafe usernames fail validation.
    """
    path = tmp_path / "resumeme.config.yaml"
    path.write_text(
        "linkedin:\n  username: example-person\ngithub:\n  username: emmeowzing\n"
        "style:\n  theme: verbose\n  themes:\n    verbose:\n      show_headline: true\n",
        encoding="utf-8",
    )
    config = load_config(path)
    assert not config.style.show_headline
    profile = Profile("example-person", "Alex", intro=["Owner @ Example"])
    assert "Owner @ Example" in render_profile(profile, config, tmp_path).read_text()
    path.write_text("linkedin:\n  username: example-person\ngithub:\n  username: bad/user\n", encoding="utf-8")

    with pytest.raises(ValidationError):
        load_config(path)


@pytest.mark.parametrize(
    "attributes", ['data-resume-headline=""', 'data-testid="profile-headline"', 'class="text-body-medium break-words"']
)
def test_capture_retains_explicit_headline_for_visibility(attributes: str) -> None:
    """
    Identify supported headline markup while preserving the original introductory text.

    Args:
        attributes (str): Supported semantic selector or established LinkedIn headline classes.

    Returns:
        None: The source profile retains the headline and the default display copy hides it.
    """
    profile = parse_profile(
        f"<main><section><h1>Alex</h1><p {attributes}>Building useful systems</p><p>Boston, MA</p></section></main>",
        "example-person",
    )
    assert profile.headline == "Building useful systems"
    assert profile.headline in profile.intro
    visible, _, _ = prepare_header(profile, Style())
    assert visible.headline == ""
    assert visible.intro == ["Boston, MA"]


@pytest.mark.parametrize("show_count", [False, True])
@pytest.mark.parametrize("show_link", [False, True])
def test_connection_display_flags_are_independent(tmp_path: Path, show_count: bool, show_link: bool) -> None:
    """
    Render a count, a concise link, both together, or neither without duplicate metadata.

    Args:
        tmp_path (Path): Isolated rendering root.
        show_count (bool): Whether the captured count should appear.
        show_link (bool): Whether the captured connections destination should appear.

    Returns:
        None: The packaged template honors both flags and leaves the source profile intact.
    """
    connections = "https://www.linkedin.com/mynetwork/invite-connect/connections/"
    duplicate = "https://www.linkedin.com/in/example-person/?isSelfProfile=true"
    profile = Profile(
        "example-person",
        "Alex",
        intro=["Staff engineer", "Contact info", "214 connections"],
        links=[Link(duplicate, duplicate), Link("214 connections", connections)],
        sections=[Section("contact", "Contact info", [Entry("Private contact block")])],
    )
    config = Config(
        LinkedIn(profile.username),
        style=Style(show_connection_count=show_count, show_connection_link=show_link),
        section_order=[key for key in DEFAULT_SECTION_ORDER if key not in (["contact"])],
    )
    source = render_profile(profile, config, tmp_path).read_text().split(r"\begin{document}", 1)[1]
    assert source.count("214 connections") == int(show_count)
    assert (connections in source) is show_link
    assert source.count(r"\textbf{LinkedIn profile}") == 1
    assert "isSelfProfile" not in source
    assert "Private contact block" not in source
    assert "Contact info" not in source

    if show_link:
        label = "214 connections" if show_count else "Connections"
        assert rf"\href{{{connections}}}{{{label}}}" in source
    elif not show_count:
        # With contact disabled, the default identity column really ends at the primary profile link.
        tail = source.split(r"\textbf{LinkedIn profile}}\par", 1)[1]
        assert "".join(tail.split()) == r"\par\addvspace{12pt}\end{document}"

    assert profile.intro[-1] == "214 connections"
    assert len(profile.links) == 2


@pytest.mark.parametrize(
    ("intro", "expected"),
    [
        (["500+ connections"], "500+ connections"),
        (["1,234", "connections"], "1,234 connections"),
        (["1.2K connections"], "1.2K connections"),
        ([], ""),
    ],
)
def test_connection_labels_handle_missing_and_split_captures(intro: list[str], expected: str) -> None:
    """
    Handle count text split across DOM nodes without fabricating absent metadata.

    Args:
        intro (list[str]): Captured header lines.
        expected (str): Observed count label, or empty for a minimal profile.

    Returns:
        None: Only connection metadata is extracted; ordinary identity prose remains intact.
    """
    profile = Profile("example-person", "Alex", intro=["Building connections across teams", *intro])
    visible, count, url = prepare_header(profile, Style(show_connection_count=True, show_connection_link=True))
    assert visible.intro == ["Building connections across teams"]
    assert count == expected
    assert url == ""


def test_header_themes_custom_templates_and_inline_links_share_visibility(tmp_path: Path) -> None:
    """
    Apply theme overrides and clean custom-template data while retaining resolved prose links.

    Args:
        tmp_path (Path): Temporary configuration and template root.

    Returns:
        None: Optional count and URL follow theme precedence, and inline external references stay clickable.
    """
    path = tmp_path / "resumeme.config.yaml"
    path.write_text(
        "linkedin:\n  username: example-person\nstyle:\n  theme: compact\n"
        "  show_connection_count: true\n  themes:\n    compact:\n"
        "      show_connection_count: false\n      show_connection_link: true\n",
        encoding="utf-8",
    )
    config = load_config(path)
    destination = "https://www.linkedin.com/mynetwork/invite-connect/connections/"
    profile = Profile(
        "example-person",
        "Alex",
        intro=["See https://lnkd.in/portfolio", "214 connections"],
        links=[Link("Portfolio", "https://lnkd.in/portfolio", "https://example.org/portfolio"), Link("214 connections", destination)],
    )
    source = render_profile(profile, config, tmp_path).read_text()
    assert r"\href{https://example.org/portfolio}" in source
    assert "214 connections" not in source
    assert rf"\href{{{destination}}}{{Connections}}" in source
    custom = tmp_path / "custom.tex.j2"
    custom.write_text("((( profile.intro )))|((( profile.links )))|((( connection_count )))|((( connection_url )))", encoding="utf-8")
    text = render_profile(profile, evolve(config, template=custom.name), tmp_path).read_text()
    assert "214 connections" not in text
    assert text.endswith(f"|[]||{destination}")


@pytest.mark.parametrize("name", ["show_connection_count", "show_connection_link"])
@pytest.mark.parametrize("theme", [False, True])
def test_connection_settings_require_booleans(tmp_path: Path, name: str, theme: bool) -> None:
    """
    Reject string booleans in both base style and inline theme settings.

    Args:
        tmp_path (Path): Temporary configuration directory.
        name (str): Connection setting under validation.
        theme (bool): Whether the invalid value is inside a theme.

    Returns:
        None: Invalid style data fails schema validation before rendering.
    """
    override = {name: "false"}
    style = {"themes": {"custom": override}} if theme else override
    path = tmp_path / "resumeme.config.yaml"
    path.write_text(yaml.safe_dump({"linkedin": {"username": "example-person"}, "style": style}), encoding="utf-8")

    with pytest.raises(ValidationError):
        load_config(path)


@pytest.mark.parametrize("label", ["", "Example & Co. logo", "EXAMPLE & CO."])
def test_header_company_logo_uses_observed_identity_and_removes_repeated_name(label: str) -> None:
    """
    Pair labeled and unlabeled logos with existing intro text while retaining the original snapshot.

    Args:
        label (str): Observed header image label, which may be absent in older captures.

    Returns:
        None: Matching branding appears once, inherits an observed destination, and does not absorb headline or location text.
    """
    url = "https://www.linkedin.com/company/example/"
    logo = Media("https://example.org/company-logo.png", alt=label, path="assets/company.png")
    portrait = Media("https://example.org/portrait.png", alt="Profile photo", path="assets/portrait.png")
    intro = ["They/them", "Engineer at Example & Co.", " Example & Co. ", "Boston", "EXAMPLE & CO"]
    profile = Profile("example-person", "Alex", intro=intro, images=[portrait, logo])
    header, badges = prepare_header_logos(profile, companies={"example & co": evolve(logo, link=url)})
    assert header.intro == intro[:-1]
    assert header.images == [portrait]
    assert badges == {"Example & Co.": evolve(logo, link=url)}
    assert profile.intro == intro
    assert profile.images == [portrait, logo]
    assert logo.link == ""


@pytest.mark.parametrize("ambiguous", [False, True])
def test_unmatched_or_ambiguous_header_logos_stay_in_the_gallery(ambiguous: bool) -> None:
    """
    Avoid assigning unrecognized or shared branding to an arbitrary company line.

    Args:
        ambiguous (bool): Whether identical branding is attributed to two visible companies.

    Returns:
        None: The header content and imagery remain intact when ownership cannot be established.
    """
    logo = Media("https://example.org/company-logo.png", path="assets/company.png")
    companies = {"first company": logo, "second company": logo} if ambiguous else {}
    profile = Profile("example-person", "Alex", intro=["First Company", "Second Company", ""], images=[logo])
    header, badges = prepare_header_logos(profile, companies=companies)
    assert header == profile
    assert badges == {}


@pytest.mark.parametrize("labeled", [False, True])
def test_header_company_logo_renders_inline_and_linked(tmp_path: Path, labeled: bool) -> None:
    """
    Use the existing employer row for header logos with direct labels or matching captured employment images.

    Args:
        tmp_path (Path): Isolated rendering directory with captured logo bytes.
        labeled (bool): Whether the header label supplies identity without an Experience section.

    Returns:
        None: One linked logo precedes one company name in the identity column, with headline and location retained.
    """
    Image.new("RGB", (20, 20), "blue").save(tmp_path / "logo.png")
    url = "https://www.linkedin.com/company/example/"
    logo = Media("https://example.org/company-logo.png", alt="Example & Co. logo", path="logo.png", link=url)
    role = Entry("Engineer", ["Example & Co.", "2020 - Present"], images=[logo])
    header_logo = logo if labeled else evolve(logo, alt="", link="")
    profile = Profile(
        "example-person",
        "Alex",
        intro=["Engineer at Example & Co.", " Example & Co. ", "Boston", "EXAMPLE & CO"],
        images=[header_logo],
        sections=[] if labeled else [Section("experience", "Experience", [role])],
    )
    source = render_profile(profile, Config(LinkedIn(profile.username), style=Style(show_headline=True)), tmp_path).read_text()
    identity = source.split(r"\begin{document}", 1)[1].split(r"\textbf{LinkedIn profile}", 1)[0]
    assert identity.count(r"\companyline{") == 1
    assert identity.count(r"\includegraphics[") == 1
    row = identity.split(r"\companyline{", 1)[1]
    assert row.index(rf"\href{{{url}}}") < row.index(r"\includegraphics[") < row.index(r"Example \& Co.")
    assert "EXAMPLE & CO" not in identity
    assert "Boston" in identity
    assert identity.index(r"Engineer at Example \& Co.") < identity.index(r"\companyline{")
