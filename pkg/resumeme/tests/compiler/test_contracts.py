"""
Exercise compiler laws over generated profiles rather than any owner's captured biography.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from copy import deepcopy
from datetime import date
from html import escape
from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from attrs import asdict
from hypothesis import given, settings
from hypothesis import strategies as st
from jsonschema import Draft202012Validator

from resumeme.compiler.asts.contributions import calendar_window
from resumeme.compiler.asts.links import discover_profile_links, safe_url
from resumeme.compiler.asts.parsing import parse_profile
from resumeme.compiler.asts.profile import Entry, Link, Media, Profile, Section, Skill, load_profile, save_profile
from resumeme.compiler.asts.sections import section_key
from resumeme.compiler.backends.latex.escaping import latex_escape
from resumeme.compiler.constants.backend import AST_PACKAGE, PROFILE_SCHEMA
from resumeme.compiler.constants.sections import DEFAULT_SECTION_ORDER
from resumeme.compiler.passes.context import resolve_dates
from resumeme.compiler.passes.experience import clean_experience, filter_experience
from resumeme.compiler.passes.ordering import order_sections
from resumeme.compiler.passes.ownership import without_ownership_metadata
from resumeme.compiler.passes.privacy import without_profile_location
from resumeme.compiler.passes.visibility import visible_profile
from resumeme.compiler.pipeline import render_profile
from resumeme.config import Config, Experience, GitHubContributions, JobSelector, LinkedIn, Style
from resumeme.exceptions import ContributionError, ProfileError

_PROFILE_SCHEMA = Draft202012Validator(json.loads(files(AST_PACKAGE).joinpath(PROFILE_SCHEMA).read_text()))
_SLUG = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=2, max_size=20)
_CHARACTER = st.characters(exclude_categories=("Cs", "Cc"))
_TEXT = st.text(alphabet=_CHARACTER, max_size=80)
_URL = _SLUG.map(lambda slug: f"https://{slug}.invalid/work")
_LINK = st.builds(Link, label=_TEXT, url=_URL, resolved_url=st.one_of(st.just(""), _URL))
_MEDIA = st.builds(Media, url=_URL, alt=_TEXT, link=st.one_of(st.just(""), _URL))
_SKILL = st.builds(Skill, name=_SLUG, endorsements=st.integers(min_value=0, max_value=1000))
_ENTRY = st.recursive(
    st.builds(
        Entry,
        title=_TEXT,
        paragraphs=st.lists(_TEXT, max_size=3),
        links=st.lists(_LINK, max_size=2),
        images=st.lists(_MEDIA, max_size=2),
        skills=st.lists(_SKILL, max_size=2),
    ),
    lambda children: st.builds(Entry, title=_TEXT, paragraphs=st.lists(_TEXT, max_size=2), positions=st.lists(children, max_size=3)),
    max_leaves=8,
)
_SECTION_KEY = st.sampled_from([*DEFAULT_SECTION_ORDER, "contact-info", "licenses-and-certifications", "custom-section"])
_PROFILE = st.builds(
    Profile,
    username=_SLUG,
    name=st.text(alphabet="abcdefghijklmnopqrstuvwxyz\u00e9\u03b1\u4e2d", min_size=1, max_size=30),
    intro=st.lists(_TEXT, max_size=3),
    headline=_TEXT,
    links=st.lists(_LINK, max_size=2),
    images=st.lists(_MEDIA, max_size=2),
    sections=st.lists(
        st.builds(Section, key=_SECTION_KEY, title=st.text(_CHARACTER, min_size=1, max_size=40), entries=st.lists(_ENTRY, max_size=3)),
        max_size=5,
    ),
)


@given(profile=_PROFILE)
@settings(max_examples=80, deadline=None)
def test_profile_normalizers_preserve_schema_source_and_fixed_points(profile: Profile) -> None:
    """
    Check total behavior, repeatability, and idempotence for context-free profile normalizers.

    Args:
        profile (Profile): Generated minimal or nested schema-valid profile with arbitrary identities and prose.

    Returns:
        None: Each normalizer preserves schema validity and its source, and reaches a fixed point after one application.
    """
    original = deepcopy(profile)
    _PROFILE_SCHEMA.validate(asdict(profile))

    for transform in (discover_profile_links, without_ownership_metadata, without_profile_location):
        first = transform(profile)
        assert transform(profile) == first
        assert transform(first) == first
        assert profile == original
        _PROFILE_SCHEMA.validate(asdict(first))


@given(entry=_ENTRY)
@settings(max_examples=60, deadline=None)
def test_experience_cleanup_preserves_source_and_reaches_a_fixed_point(entry: Entry) -> None:
    """
    Verify nested role cleanup independently of employer names and source text.

    Args:
        entry (Entry): Generated finite role tree.

    Returns:
        None: Repeated cleanup has no further effect and captured records stay untouched.
    """
    original = deepcopy(entry)
    cleaned = clean_experience(entry)
    assert clean_experience(cleaned) == cleaned
    assert clean_experience(entry) == cleaned
    assert entry == original


@given(profile=_PROFILE, enabled=st.lists(_SECTION_KEY, unique=True, max_size=8))
@settings(max_examples=60, deadline=None)
def test_visibility_is_closed_and_ordering_is_stable(profile: Profile, enabled: list[str]) -> None:
    """
    Exercise empty, unknown, aliased, and reordered section selections.

    Args:
        profile (Profile): Arbitrary schema-valid source profile.
        enabled (list[str]): Explicit configured section order, including the empty selection.

    Returns:
        None: Disabled sections stay absent, stable sorting is idempotent, and inputs are preserved.
    """
    original = deepcopy(profile)
    config = Config(LinkedIn(profile.username), section_order=enabled)
    displayed = visible_profile(profile, config)
    ordered = order_sections(displayed.sections, enabled)
    assert all(section.key in {section_key(key) for key in enabled} for section in ordered)
    assert order_sections(ordered, enabled) == ordered
    assert visible_profile(displayed, config) == displayed
    assert profile == original
    _PROFILE_SCHEMA.validate(asdict(displayed))


@given(
    pieces=st.lists(
        st.sampled_from(["LinkedIn helped me get this job", "helped me get this job", "LINKEDIN HELPED ME GET THIS JOB!"]),
        min_size=1,
        max_size=8,
    ),
    separator=st.sampled_from([" ", "  ", "\t", "\u00a0"]),
)
def test_attribution_grammar_accepts_repetition_without_consuming_authored_prose(pieces: list[str], separator: str) -> None:
    """
    Match complete repeated platform labels instead of enumerating observed duplicate strings.

    Args:
        pieces (list[str]): Full or accessibility-shortened badge labels in any order.
        separator (str): Captured whitespace between labels.

    Returns:
        None: Pure UI rows and links disappear while a sentence containing the same words survives.
    """
    badge = separator.join(pieces)
    prose = f"My colleague said {badge}, and we built a service together."
    entry = Entry("A role", [badge, prose], links=[Link(badge, "https://example.invalid/jobs")])
    cleaned = clean_experience(entry)
    assert cleaned.paragraphs == [prose]
    assert cleaned.links == []


@given(owner=_SLUG, host=_SLUG, depth=st.integers(min_value=0, max_value=3), shared=st.booleans())
def test_ownership_cleanup_handles_split_records_and_redirects(owner: str, host: str, depth: int, shared: bool) -> None:
    """
    Track managed previews across sibling records, nested entries, and redirect aliases for arbitrary owners.

    Args:
        owner (str): Generated LinkedIn username.
        host (str): Generated release host unrelated to any repository or account.
        depth (int): Number of nesting layers surrounding the preview.
        shared (bool): Whether personal prose independently references the same destination.

    Returns:
        None: Only exclusively managed media is removed, and every source record and other section remains intact.
    """
    short = f"https://{host}.invalid/go"
    destination = f"https://{host}.invalid/releases"
    image = Media(f"https://{host}.invalid/preview.png", link=destination)
    preview = Entry(images=[image], links=[Link("Release preview", short, destination)])

    for _ in range(depth):
        preview = Entry(positions=[preview])

    prose = Entry("Personal work", [f"Read my work at {destination}."] if shared else ["I build systems."])
    metadata = Entry("resume  signature: SHA256:abcdef", [f"RELEASES: {short}"])
    source = Profile(
        owner, "A person", sections=[Section(" ABOUT ", "About", [prose, metadata, preview]), Section("projects", "Projects", [preview])]
    )
    original = deepcopy(source)
    result = without_ownership_metadata(source)
    assert result.sections[0].entries == ([prose, preview] if shared else [prose])
    assert result.sections[1] == source.sections[1]
    assert without_ownership_metadata(result) == result
    assert source == original


@given(value=st.text())
def test_lexical_boundaries_return_defined_results_for_arbitrary_strings(value: str) -> None:
    """
    Reject malformed URLs safely and escape text without assuming a particular alphabet.

    Args:
        value (str): Arbitrary Unicode input, including malformed URL syntax.

    Returns:
        None: Lexical helpers return strings deterministically instead of leaking URL parser exceptions.
    """
    assert isinstance(safe_url(value), str)
    assert latex_escape(value) == latex_escape(value)


@pytest.mark.parametrize("value", ["http://[", "https://[broken/", "https://\uff0f.invalid/"])
def test_malformed_url_delimiters_are_rejected(value: str) -> None:
    """
    Cover malformed authorities that can fail during URL joining before splitting.

    Args:
        value (str): Non-navigable source reference.

    Returns:
        None: Invalid link syntax has the documented empty result.
    """
    assert safe_url(value) == ""


@given(today=st.dates(), pinned=st.dates())
def test_reference_date_resolution_is_pure_and_preserves_explicit_endpoints(today: date, pinned: date) -> None:
    """
    Bind relative settings once without overwriting user-selected dates or mutating configuration.

    Args:
        today (date): Explicit orchestration date.
        pinned (date): Independent user-selected employment endpoint.

    Returns:
        None: Resolution is deterministic and idempotent even if a later caller supplies another date.
    """
    config = Config(LinkedIn("someone"), experience=Experience(as_of=pinned.isoformat()))
    original = deepcopy(config)
    resolved = resolve_dates(config, today=today)
    assert resolved.experience.as_of == pinned.isoformat()
    assert resolved.github.contributions.as_of == today.isoformat()
    assert resolve_dates(resolved, today=date.min) == resolved
    assert config == original


def test_missing_temporal_inputs_fail_with_domain_diagnostics() -> None:
    """
    Refuse to invent date-dependent compiler inputs or leak calendar arithmetic errors.

    Returns:
        None: Unbound windows and unsupported calendar ranges raise explicit domain errors.
    """
    with pytest.raises(ProfileError, match="reference date"):
        filter_experience([], Experience(last_years=5))

    with pytest.raises(ContributionError, match="reference date"):
        calendar_window(GitHubContributions())

    with pytest.raises(ContributionError, match="year 1"):
        calendar_window(GitHubContributions(months=1), today=date.min)

    # An identity filter is independent of the clock and does not silently remove a future-dated position.
    future = Entry("Future role", ["An employer", "Jan 2099 - Present"])
    assert filter_experience([future], Experience(disable=[JobSelector(title="Other role")]), today=date(2020, 1, 1)) == [future]


@given(owner=_SLUG, name=_SLUG, prose=_TEXT)
@settings(max_examples=20, deadline=None)
def test_html_to_tex_repeats_with_the_same_explicit_inputs(owner: str, name: str, prose: str) -> None:
    """
    Compile generated HTML through the profile schema and display passes to deterministic TeX.

    Args:
        owner (str): Arbitrary owner whose identity must survive parsing.
        name (str): Arbitrary profile name.
        prose (str): Authored text containing Unicode and potential markup delimiters.

    Returns:
        None: Parsed sources remain intact and compilation emits identical bytes after a schema-validated JSON round trip.
    """
    html = f"<main><section><h1>{escape(name)}</h1></section><section><h2>About</h2><p>{escape(prose)}</p></section></main>"
    profile = parse_profile(html, owner)
    original = deepcopy(profile)
    config = Config(LinkedIn(owner), section_order=["about"], style=Style(skills_word_cloud=False))
    _PROFILE_SCHEMA.validate(asdict(profile))

    # Each generated example owns its output directory; no browser, network, host profile, or TeX installation is involved.
    with TemporaryDirectory() as directory:
        root = Path(directory)
        first = render_profile(profile, config, root, today=date(2026, 1, 1)).read_bytes()
        assert render_profile(profile, config, root, today=date(2026, 1, 1)).read_bytes() == first
        snapshot = root / "profile.json"
        save_profile(profile, snapshot)
        restored = load_profile(snapshot, owner)
        assert restored == profile
        assert render_profile(restored, config, root, today=date(2026, 1, 1)).read_bytes() == first

    assert profile == original


def test_rendering_is_independent_of_python_hash_seed(tmp_path: Path) -> None:
    """
    Compare TeX and skill assets across fresh processes with different set and dictionary hash seeds.

    Args:
        tmp_path (Path): Isolated configuration, snapshot, and generated output directory.

    Returns:
        None: The same synthetic inputs produce identical TeX and PNG bytes in independent processes.
    """
    profile = Profile(
        "arbitrary-owner",
        "Another Person",
        sections=[
            Section("about", "About", [Entry("I build Python and Rust services.")]),
            Section("skills", "Skills", [Entry("Tools", skills=[Skill("Python", 7), Skill("Rust", 7), Skill("Go")])]),
            Section(
                "projects",
                "Projects",
                [Entry(name, links=[Link(name, f"https://example.invalid/{name.lower()}")]) for name in ("Beta", "Alpha", "Beta")],
            ),
        ],
    )
    config = tmp_path / "resumeme.config.yaml"
    config.write_text(
        "linkedin:\n  username: arbitrary-owner\nproject_filter: null\n"
        "section_order: [about, projects, skills]\nexperience:\n  as_of: '2026-01-01'\n"
        "github:\n  contributions:\n    as_of: '2026-01-01'\n",
        encoding="utf-8",
    )
    save_profile(profile, tmp_path / "data/profile.json")
    observed: list[dict[str, bytes]] = []

    for seed in ("1", "17"):
        result = subprocess.run(
            [sys.executable, "-m", "resumeme.cli", "--config", str(config), "render"],
            env=dict(os.environ, PYTHONHASHSEED=seed, MPLCONFIGDIR=str(tmp_path / ".cache/matplotlib")),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        output = tmp_path / "tex"
        observed.append({str(path.relative_to(output)): path.read_bytes() for path in output.rglob("*") if path.is_file()})

    assert observed[0] == observed[1]
