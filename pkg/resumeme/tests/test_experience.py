"""
Verify inclusive employment windows and job exclusions across capture and rendering.
"""

from __future__ import annotations

import json
from datetime import date
from typing import TYPE_CHECKING

import pytest
from attrs import evolve
from jsonschema import ValidationError

from resumeme.compiler.asts.dates import EmploymentPeriod, employment_period
from resumeme.compiler.asts.parsing import parse_detail
from resumeme.compiler.asts.profile import Entry, Link, Media, Profile, Section, load_profile, save_profile
from resumeme.compiler.constants.sections import DEFAULT_SECTION_ORDER
from resumeme.compiler.passes.experience import clean_experience, filter_experience
from resumeme.compiler.pipeline import render_profile
from resumeme.config import Config, Experience, JobSelector, LinkedIn, load_config

if TYPE_CHECKING:
    from pathlib import Path


def test_job_attribution_cleanup_preserves_prose_and_grouped_snapshots(tmp_path: Path) -> None:
    """
    Remove complete and accessibility attribution rows from both flattened and structured role views.

    Args:
        tmp_path (Path): Isolated template and rendering directory.

    Returns:
        None: Default and custom templates omit UI attribution while substantive text and original records remain intact.
    """
    paragraphs = [
        "2020 - Present",
        "Boston, Massachusetts, United States",
        "LinkedIn helped me get this job",
        "helped me get this job",
        "- Built services\n LINKEDIN  helped me get this job.\n- Mentored engineers",
        "My colleague helped me get this job and we built the platform together.",
    ]
    role = Entry("Engineer", paragraphs, links=[Link("LinkedIn helped me get this job", "https://www.linkedin.com/jobs/")])
    group = Entry("Example Co", [role.title, *paragraphs], positions=[role])
    visible = clean_experience(group)
    assert visible.positions[0].paragraphs == [*paragraphs[:2], "- Built services\n- Mentored engineers", paragraphs[-1]]
    assert visible.positions[0].links == []
    assert visible.paragraphs == [role.title, *visible.positions[0].paragraphs]
    assert group.positions == [role]
    assert role.paragraphs == paragraphs
    assert len(role.links) == 1
    profile = Profile("example-person", "Alex", sections=[Section("experience", "Experience", [group])])
    config = Config(LinkedIn(profile.username))
    custom = tmp_path / "custom.tex.j2"
    custom.write_text("((( profile.sections )))", encoding="utf-8")

    # Cleanup precedes template selection, so custom rendering cannot accidentally restore captured interface text.
    for template in (None, custom.name):
        source = render_profile(profile, evolve(config, template=template), tmp_path).read_text()
        assert "LinkedIn helped me" not in source
        assert "LINKEDIN" not in source
        assert paragraphs[-1] in source
        assert "Built services" in source
        assert "Mentored engineers" in source


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Jan 2010 - Present \u00b7 16 yrs", EmploymentPeriod(date(2010, 1, 1), None)),
        ("September 2019 \u2013 Oct. 2021 \u00b7 2 yrs", EmploymentPeriod(date(2019, 9, 1), date(2021, 10, 31))),
        ("2010\u20142021", EmploymentPeriod(date(2010, 1, 1), date(2021, 12, 31))),
        ("2020-02 - 2020-02", EmploymentPeriod(date(2020, 2, 1), date(2020, 2, 29))),
        ("2021-10-07 - 2026-10-07", EmploymentPeriod(date(2021, 10, 7), date(2026, 10, 7))),
        ("Built services from 2010 - 2021", None),
        ("2020 - 2010", None),
        ("Unknown 2020 - Present", None),
        ("2020-99 - Present", None),
        ("0000 - Present", None),
        ("2021-02-29 - Present", None),
        ("Dates unavailable", None),
    ],
)
def test_employment_date_precision(text: str, expected: EmploymentPeriod | None) -> None:
    """
    Preserve date precision and distinguish employment metadata from descriptive prose.

    Args:
        text (str): Displayed employment line.
        expected (EmploymentPeriod | None): Inclusive bounds, or unknown when the line cannot be interpreted.

    Returns:
        None: Calendar bounds and invalid-date handling match the contract.
    """
    assert employment_period(text) == expected


@pytest.mark.parametrize(
    ("period", "included"),
    [
        ("2010 - Present", True),
        ("2010 - Oct 2021", True),
        ("2010 - 2021-10-07", True),
        ("2010 - 2021-10-06", False),
        ("2010 - Sep 2021", False),
        ("2010 - 2021", True),
        ("2026-10-07 - Present", True),
        ("2026-10-08 - Present", False),
        ("2027 - 2029", False),
        ("Dates unavailable", True),
        ("", True),
    ],
)
def test_trailing_years_includes_any_overlap(period: str, included: bool) -> None:
    """
    Include jobs spanning the cutoff and its boundary day, without shortening their descriptions.

    Args:
        period (str): Captured date metadata, possibly absent or unsupported.
        included (bool): Whether the job overlaps the fixed five-year window.

    Returns:
        None: Inclusion uses the whole employment interval and leaves source records unchanged.
    """
    job = Entry("Engineer", ["Example \u00b7 Full-time", period, "Complete description"])
    settings = Experience(last_years=5, as_of="2026-10-07")
    assert filter_experience([job], settings) == ([job] if included else [])
    assert job.paragraphs[-1] == "Complete description"


def test_default_clock_override_and_leap_day() -> None:
    """
    Use the current date by default, accept a fixed endpoint, and handle leap anniversaries.

    Returns:
        None: Calendar-year subtraction and explicit configuration take precedence correctly.
    """
    jobs = [Entry("Recent", ["Example", "2020 - Feb 2023"]), Entry("Earlier", ["Example", "2020 - Jan 2023"])]
    assert filter_experience(jobs, Experience(last_years=1), today=date(2024, 2, 29)) == jobs[:1]
    assert filter_experience(jobs, Experience(last_years=1, as_of="2023-01-01"), today=date(2090, 1, 1)) == jobs
    assert filter_experience(jobs, Experience(), today=date(2090, 1, 1)) == jobs
    assert filter_experience(jobs, Experience(last_years=9999), today=date(2024, 2, 29)) == jobs


def test_job_selectors_match_all_supplied_fields() -> None:
    """
    Distinguish matching titles at different employers and give exclusions precedence over dates.

    Returns:
        None: Explicit rules match normalized exact identities without substring matching.
    """
    jobs = [
        Entry("DevOps Engineer", ["HqO \u00b7 Full-time", "2020 - Present"]),
        Entry("DevOps Engineer", ["Example \u00b7 Full-time", "2020 - Present"]),
        Entry("Senior DevOps Engineer", ["HqO \u00b7 Full-time", "2020 - Present"]),
    ]
    settings = Experience(disable=[JobSelector(title=" devops   ENGINEER ", company="hqo")], last_years=5, as_of="2026-10-07")
    assert filter_experience(jobs, settings) == jobs[1:]
    assert filter_experience(jobs, Experience(disable=[JobSelector(company="HqO")])) == jobs[1:2]
    assert filter_experience(jobs, Experience(disable=[JobSelector(title="DevOps Engineer")])) == jobs[2:]
    assert filter_experience(jobs, Experience(disable=[JobSelector(title="Engineer")])) == jobs


@pytest.mark.parametrize("custom_template", [False, True])
def test_grouped_roles_filter_before_templates_assets_and_skills(tmp_path: Path, custom_template: bool) -> None:
    """
    Exclude individual roles and all their associated content while preserving the company's current role.

    Args:
        tmp_path (Path): Temporary project directory.
        custom_template (bool): Whether to inspect the full profile supplied to a custom template.

    Returns:
        None: Removed role text, media, links, and skill tags do not reach either template or cloud input.
    """
    html = """<main><h2>Experience</h2><ul><li class="artdeco-list__item"><p>Example Systems</p>
        <ul><li><p>Staff Engineer</p><p>Jan 2020 \u2013 Present</p><p>Current infrastructure.</p>
        <a href="/in/example-person/skill-associations-details/">Rust</a></li>
        <li><p>Senior Engineer</p><p>2010 \u2013 Sep 2021</p><p>Removed narrative.</p>
        <a href="https://example.org/removed">Removed project</a><img src="https://example.org/removed.png" alt="Removed figure">
        <a href="/in/example-person/skill-associations-details/">Python</a></li></ul></li></ul></main>"""
    section = parse_detail(html, "experience", "Experience")
    assert [position.title for position in section.entries[0].positions] == ["Staff Engineer", "Senior Engineer"]
    profile = Profile("example-person", "Alex", sections=[section])
    snapshot = tmp_path / "profile.json"
    save_profile(profile, snapshot)

    # Compare the persisted input after rendering as well as the output, since filters must remain reversible without recapture.
    original = snapshot.read_bytes()
    assert load_profile(snapshot, profile.username) == profile
    config = Config(LinkedIn(profile.username), experience=Experience(last_years=5, as_of="2026-10-07"))

    if custom_template:
        (tmp_path / "custom.tex.j2").write_text("((( profile )))", encoding="utf-8")
        config = evolve(config, template="custom.tex.j2")

    rendered = render_profile(profile, config, tmp_path).read_text()
    assert "Staff Engineer" in rendered
    assert "Example Systems" in rendered

    # Assert across text, URLs, dates, and skill metadata so a hidden role cannot survive through another template field.
    for hidden in ("Senior Engineer", "Removed", "removed", "Python", "Sep 2021"):
        assert hidden not in rendered

    assert json.loads((tmp_path / "tex/skills.weights.json").read_text()) == {"Rust": {"references": 1, "endorsements": 0, "weight": 1}}
    assert all(asset.name.startswith("skills-") for asset in (tmp_path / "tex/assets").iterdir())
    assert snapshot.read_bytes() == original
    explicit = Experience(disable=[JobSelector(title="Senior Engineer", company="Example Systems")])
    assert filter_experience(section.entries, explicit) == filter_experience(section.entries, config.experience)
    assert filter_experience(section.entries, Experience(disable=[JobSelector(company="Example Systems")])) == []


def test_old_grouped_snapshots_do_not_silently_leak_excluded_roles() -> None:
    """
    Support whole-group selection in old snapshots and request missing boundaries for partial selection.

    Returns:
        None: Legacy input stays valid while ambiguous role ownership fails visibly.
    """
    group = Entry("Example", ["Staff", "2020 - Present", "Current description", "Junior", "2010 - 2019", "Old description"])
    assert filter_experience([group], Experience()) == [group]
    assert filter_experience([group], Experience(disable=[JobSelector(company="Example")])) == []

    with pytest.raises(ValueError, match="Run `resumeme capture`"):
        filter_experience([group], Experience(last_years=5, as_of="2026-10-07"))

    with pytest.raises(ValueError, match="Run `resumeme capture`"):
        filter_experience([group], Experience(disable=[JobSelector(title="Junior", company="Example")]))

    historical = evolve(group, paragraphs=["Staff", "2018 - 2020", "Junior", "2010 - 2018"])
    assert filter_experience([historical], Experience(last_years=5, as_of="2026-10-07")) == []


def test_grouped_roles_without_dates_remain_selectable() -> None:
    """
    Retain an undated sibling and allow its explicit exclusion independently of dated roles.

    Returns:
        None: Partial date metadata never causes an undated role to disappear or become company context.
    """
    html = """<main><ul><li class="artdeco-list__item"><p>Example</p><ul>
        <li><p>Engineer</p><p>2020 - Present</p><p>Infrastructure</p></li>
        <li><p>Consultant</p><p>Dates unavailable</p><p>Advice</p></li></ul></li></ul></main>"""
    entries = parse_detail(html, "experience", "Experience").entries
    assert [position.title for position in entries[0].positions] == ["Engineer", "Consultant"]
    settings = Experience(disable=[JobSelector(title="Engineer")], last_years=5, as_of="2026-10-07")
    selected = filter_experience(entries, settings)
    assert [position.title for position in selected[0].positions] == ["Consultant"]
    assert selected[0].paragraphs == ["Consultant", "Dates unavailable", "Advice"]


def test_empty_profiles_and_disabled_experience(tmp_path: Path) -> None:
    """
    Omit empty cards and apply whole-section exclusions before per-job rules.

    Args:
        tmp_path (Path): Temporary output directory.

    Returns:
        None: Identity-only output and unrelated sections do not depend on employment metadata.
    """
    job = Entry("Engineer", ["Example", "2010 - 2015"], images=[Media("https://example.org/missing.png")])
    profile = Profile(
        "example-person",
        "Alex",
        sections=[Section("experience", "Experience", [job]), Section("education", "Education", [evolve(job, images=[])])],
    )
    config = Config(LinkedIn(profile.username), experience=Experience(last_years=5, as_of="2026-10-07"))
    rendered = render_profile(profile, config, tmp_path).read_text()
    assert "Alex" in rendered
    assert r"\sectiontitle{Experience}" not in rendered
    assert r"\sectiontitle{Education}" in rendered
    assert "2010 - 2015" in rendered
    assert filter_experience([], config.experience) == []
    ambiguous = Entry("Example", ["Staff", "2020 - Present", "Junior", "2010 - 2019"])
    hidden = evolve(profile, sections=[Section("experience", "Experience", [ambiguous])])
    assert render_profile(
        hidden, evolve(config, section_order=[key for key in DEFAULT_SECTION_ORDER if key not in (["experience"])]), tmp_path
    ).exists()


@pytest.mark.parametrize(
    "settings",
    [
        "{last_years: 0}",
        "{last_years: -5}",
        "{last_years: true}",
        "{last_years: 1.5}",
        "{last_years: '5'}",
        "{disable: [Engineer]}",
        "{disable: [{}]}",
        "{disable: [{title: ' '}]}",
        "{disable: [{company: null}]}",
        "{disable: [{title: Engineer, employer: Example}]}",
        "{as_of: '2026-02-30'}",
        "{last_year: 5}",
    ],
)
def test_experience_config_rejects_invalid_filters(tmp_path: Path, settings: str) -> None:
    """
    Reject ambiguous selectors, invalid dates, and nonintegral windows before rendering.

    Args:
        tmp_path (Path): Temporary configuration directory.
        settings (str): Invalid YAML experience block.

    Returns:
        None: Configuration validation fails instead of silently widening or narrowing the job list.
    """
    path = tmp_path / "resumeme.config.yaml"
    path.write_text(f"linkedin:\n  username: example-person\nexperience: {settings}\n", encoding="utf-8")

    with pytest.raises(ValidationError):
        load_config(path)


def test_experience_config_defaults_and_roundtrip(tmp_path: Path) -> None:
    """
    Structure the documented YAML example and preserve username-only configuration defaults.

    Args:
        tmp_path (Path): Temporary configuration directory.

    Returns:
        None: All jobs remain enabled by default and the documented selectors are usable.
    """
    path = tmp_path / "resumeme.config.yaml"
    path.write_text("linkedin:\n  username: example-person\n", encoding="utf-8")
    assert load_config(path).experience == Experience()

    with path.open("a", encoding="utf-8") as stream:
        stream.write("experience:\n  disable: [{title: DevOps Engineer, company: HqO}]\n  last_years: 5\n  as_of: '2026-10-07'\n")

    assert load_config(path).experience == Experience([JobSelector("DevOps Engineer", "HqO")], 5, "2026-10-07")
