"""
Verify employer evidence, independent summary variants, and exact CI publication inputs.
"""

from __future__ import annotations

import hashlib
import json
import runpy
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import requests
import yaml
from attrs import asdict, evolve
from jsonschema import ValidationError

from resumeme.cli import main
from resumeme.codex.companies import company_config, load_company, prepare_companies, render_companies
from resumeme.codex.request import prepare_summary
from resumeme.compiler.asts.profile import Entry, Profile, Section, save_profile
from resumeme.compiler.passes.summary import summary_digest
from resumeme.config import Capture, Codex, CompanyTarget, Config, LinkedIn, load_config
from resumeme.github.company_artifacts import restore_companies, stage_companies

if TYPE_CHECKING:
    from pytest import MonkeyPatch


@pytest.fixture
def profile() -> Profile:
    """
    Supply a complete applicant without employer-specific claims.

    Returns:
        Profile: Captured About and one professional role.
    """
    return Profile(
        "example-person",
        "Alex Example",
        sections=[
            Section("about", "About", [Entry("Original About")]),
            Section("experience", "Experience", [Entry("Engineer", ["Built platforms"])]),
        ],
    )


@pytest.fixture
def config() -> Config:
    """
    Select two jobs at one employer using explicit source text and independent preferences.

    Returns:
        Config: Enabled matrix with no need for external HTTP requests.
    """
    targets = [
        CompanyTarget(
            "example-company",
            f"https://www.linkedin.com/jobs/view/{number}/",
            context=f"Focus on {focus}.",
            company_context="An engineering company building reliable developer platforms.",
            job_context=f"A senior engineering position with a focus on {focus} and collaboration.",
        )
        for number, focus in [(123, "reliability"), (456, "developer experience")]
    ]
    return Config(LinkedIn("example-person"), codex=Codex(enabled=True, companies=targets))


def _responses(root: Path, profile: Profile, config: Config) -> Path:
    """
    Simulate structured model responses to the actual generated requests.

    Args:
        root (Path): Isolated configuration directory.
        profile (Profile): Applicant whose evidence is bound into each response.
        config (Config): Generic settings and explicit company descriptions.

    Returns:
        Path: Root summary bundle containing the generic response and employer subdirectories.
    """
    generic = prepare_summary(profile, config, root)
    directories = [generic, *prepare_companies(profile, config, root)]

    for index, directory in enumerate(directories):
        company = load_company(directory / "company.json", config.codex.companies[index - 1]) if index else None
        label = f"Tailored variant {index}" if index else "Generic summary"
        (directory / "summary.json").write_text(
            json.dumps(
                {
                    "username": profile.username,
                    "source_digest": summary_digest(profile, config, company),
                    "about": label + " About",
                    "headline": label + " Headline",
                }
            )
        )

    return generic


def test_company_config_keeps_distinct_jobs_and_rejects_duplicate_destinations(config: Config, tmp_path: Path) -> None:
    """
    Resolve readable job directories and reject links that would overwrite the same output.

    Args:
        config (Config): Two targets at one company.
        tmp_path (Path): Configuration directory.

    Returns:
        None: Tracking parameters cannot create duplicate outputs and external jobs get stable URL-derived keys.
    """
    path = tmp_path / "resumeme.config.yaml"
    path.write_text(yaml.safe_dump(asdict(config)))
    loaded = load_config(path)
    assert [target.key for target in loaded.codex.companies] == ["example-company/job-123", "example-company/job-456"]
    assert company_config(config, loaded.codex.companies[0]).output.pdf == "single-origin/example-company/job-123/resume.pdf"
    assert config.output.pdf == "resume.pdf"
    external = evolve(loaded.codex.companies[0], job_url="https://careers.example.org/openings?job=engineer")
    assert external.key.endswith(hashlib.sha256(external.job_url.encode()).hexdigest()[:16])
    duplicate = evolve(loaded.codex.companies[0], job_url="https://www.linkedin.com/jobs/view/platform-engineer-123/?tracking=abc")
    path.write_text(yaml.safe_dump(asdict(evolve(config, codex=evolve(config.codex, companies=[loaded.codex.companies[0], duplicate])))))

    with pytest.raises(ValueError, match="distinct company/job"):
        load_config(path)


@pytest.mark.parametrize(
    "target",
    [
        {"username": "example"},
        {"username": "../../outside", "job_url": "https://example.org/job"},
        {"username": "example", "job_url": "http://example.org/job"},
        {"username": "example", "job_url": "https://example.org/job", "job_context": 7},
        {"username": "example", "job_url": "https://example.org/job", "api_key": "secret"},
    ],
)
def test_invalid_company_configuration_fails_before_acquisition(tmp_path: Path, target: dict[str, object]) -> None:
    """
    Reject missing job links, unsafe slugs, non-HTTPS links, unknown fields, and malformed context.

    Args:
        tmp_path (Path): Configuration directory.
        target (dict[str, object]): Invalid target entry.

    Returns:
        None: Schema validation rejects the target before any request or file creation.
    """
    path = tmp_path / "resumeme.config.yaml"
    path.write_text(yaml.safe_dump({"linkedin": {"username": "example"}, "codex": {"companies": [target]}}))

    with pytest.raises(ValidationError):
        load_config(path)


def test_prompts_separate_applicant_facts_from_employer_requirements(profile: Profile, config: Config, tmp_path: Path) -> None:
    """
    Keep the generic request independent and bind each target to its own context and descriptions.

    Args:
        profile (Profile): Shared applicant capture.
        config (Config): Two employer targets with different preferences.
        tmp_path (Path): Request output directory.

    Returns:
        None: Generic evidence excludes targets; each tailored digest changes with employer content and preferences.
    """
    bundle = _responses(tmp_path, profile, config)
    generic = (bundle / "prompt.txt").read_text()
    assert "example-company" not in generic and "developer experience" not in generic
    assert summary_digest(profile, config) == summary_digest(profile, evolve(config, codex=evolve(config.codex, companies=[])))
    first, second = [load_company(bundle / "companies" / target.key / "company.json", target) for target in config.codex.companies]
    assert summary_digest(profile, config, first) != summary_digest(profile, config, second)
    assert summary_digest(profile, config, first) != summary_digest(profile, config, evolve(first, job="Different requirements"))
    prompt = (bundle / "companies" / first.target.key / "prompt.txt").read_text()
    assert "Built platforms" in prompt and first.company in prompt and first.job in prompt
    assert "never qualifications the applicant possesses" in prompt

    with pytest.raises(ValueError, match="target changed"):
        load_company(bundle / "companies" / first.target.key / "company.json", second.target)


@pytest.mark.parametrize("change", ["company", "response", "preferences"])
def test_stale_or_cross_target_summaries_fail_before_output(profile: Profile, config: Config, tmp_path: Path, change: str) -> None:
    """
    Reject changed context, another target's response, and changed configuration without replacing output.

    Args:
        profile (Profile): Applicant capture.
        config (Config): Target list.
        tmp_path (Path): Prepared request bundle.
        change (str): Corruption or stale input to introduce.

    Returns:
        None: No company source or PDF is generated from mismatched evidence.
    """
    bundle = _responses(tmp_path, profile, config) / "companies"
    first, second = [bundle / target.key for target in config.codex.companies]

    if change == "company":
        raw = json.loads((first / "company.json").read_text())
        raw["job"] = "Changed job description"
        (first / "company.json").write_text(json.dumps(raw))
    elif change == "response":
        (first / "summary.json").write_bytes((second / "summary.json").read_bytes())
    else:
        target = evolve(config.codex.companies[0], context="Changed preferences")
        config = evolve(config, codex=evolve(config.codex, companies=[target, config.codex.companies[1]]))

    with pytest.raises(ValueError):
        render_companies(profile, config, tmp_path, bundle, compile_documents=False)

    assert not (tmp_path / ".cache/single-origin").exists()


def test_cli_builds_generic_and_company_outputs_independently(
    profile: Profile, config: Config, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """
    Exercise the public command with shared input and separate generated copy and output paths.

    Args:
        profile (Profile): Captured applicant.
        config (Config): Generic and employer settings.
        tmp_path (Path): Configuration and artifact directory.
        monkeypatch (MonkeyPatch): Substitute only external TeX compilation.

    Returns:
        None: Three distinct outputs preserve the original capture and generic copy.
    """
    path = tmp_path / "resumeme.config.yaml"
    path.write_text(yaml.safe_dump(asdict(config)))
    save_profile(profile, tmp_path / config.output.profile)
    before = (tmp_path / config.output.profile).read_bytes()
    _responses(tmp_path, profile, config)

    def compile_stub(source: Path, settings: Config, root: Path) -> Path:
        """
        Record the compiled source while preserving the real compiler's selected output contract.

        Args:
            source (Path): Actual rendered TeX with the selected summary.
            settings (Config): Per-document output configuration.
            root (Path): Fixture project directory.

        Returns:
            Path: Fixture PDF containing the source for content assertions.
        """
        destination = root / settings.output.pdf
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"%PDF-fixture\n" + source.read_bytes())
        return destination

    monkeypatch.setattr("resumeme.cli.compile_pdf", compile_stub)
    monkeypatch.setattr("resumeme.codex.companies.compile_pdf", compile_stub)
    assert (
        main(["--config", str(path), "build", "--summary", ".cache/codex/summary.json", "--company-summaries", ".cache/codex/companies"])
        == 0
    )
    generic = (tmp_path / "resume.pdf").read_text()
    assert "Generic summary About" in generic and "Tailored variant" not in generic

    for index, target in enumerate(config.codex.companies, 1):
        output = (tmp_path / company_config(config, target).output.pdf).read_text()
        assert f"Tailored variant {index} About" in output and "Generic summary" not in output

    assert (tmp_path / config.output.profile).read_bytes() == before


def test_public_context_fetches_company_once_and_retries_transient_errors(
    profile: Profile, config: Config, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """
    Acquire real page-shaped evidence through the existing bounded requests interface.

    Args:
        profile (Profile): Applicant capture.
        config (Config): Two jobs at one employer.
        tmp_path (Path): Request cache.
        monkeypatch (MonkeyPatch): Replace network responses with public-page fixtures.

    Returns:
        None: One shared company fetch and both jobs produce independent context after a bounded retry.
    """
    targets = [evolve(target, company_context="", job_context="") for target in config.codex.companies]
    config = evolve(config, codex=evolve(config.codex, companies=targets), capture=Capture(retry_attempts=2, retry_backoff_seconds=0))
    calls: list[str] = []

    def fetch(session: requests.Session, url: str, timeout: int) -> tuple[bytes, str]:
        """
        Supply JSON-LD job descriptions and the LinkedIn About description after one connection failure.

        Args:
            session (requests.Session): Dedicated unauthenticated HTTP session.
            url (str): Requested public page.
            timeout (int): Configured timeout.

        Returns:
            tuple[bytes, str]: Fixture HTML and its unchanged destination.
        """
        calls.append(url)
        assert session.trust_env is False and timeout == config.capture.page_timeout_seconds

        if len(calls) == 1:
            raise requests.ConnectionError("Temporary connection failure")

        if "/company/" in url:
            return (
                b'<h1>Example</h1><p data-test-id="about-us__description">We build reliable developer platforms for engineering teams.</p>',
                url,
            )

        return (
            b'<script type="application/ld+json">{"@graph":[{"@type":"JobPosting","title":"Senior Platform Engineer",'
            b'"description":"Build reliable services and collaborate with application engineers."}]}</script>',
            url,
        )

    monkeypatch.setattr("resumeme.codex.companies.fetch_public", fetch)
    directories = prepare_companies(profile, config, tmp_path)
    assert len(directories) == 2 and len(calls) == 4
    assert all("Build reliable services" in (directory / "company.json").read_text() for directory in directories)
    assert all("Senior Platform Engineer" in (directory / "company.json").read_text() for directory in directories)


@pytest.mark.parametrize(
    "destination,html", [("https://www.linkedin.com/authwall", b"Login"), ("https://example.org/job", b"<h1>Sign in</h1>")]
)
def test_login_or_missing_descriptions_require_explicit_overrides(
    profile: Profile, config: Config, tmp_path: Path, monkeypatch: MonkeyPatch, destination: str, html: bytes
) -> None:
    """
    Refuse to generate employer-aware copy from a URL alone or a login page.

    Args:
        profile (Profile): Applicant capture.
        config (Config): Valid company settings.
        tmp_path (Path): Request cache.
        monkeypatch (MonkeyPatch): Substitute a blocked public page.
        destination (str): Final HTTP destination.
        html (bytes): Unsupported or blocked page body.

    Returns:
        None: Preparation fails with an actionable override option before writing a company prompt.
    """
    target = evolve(config.codex.companies[0], job_context="")
    config = evolve(config, codex=evolve(config.codex, companies=[target]))
    monkeypatch.setattr("resumeme.codex.companies.fetch_public", lambda *args: (html, destination))

    with pytest.raises(ValueError, match="job_context"):
        prepare_companies(profile, config, tmp_path)

    assert not (tmp_path / ".cache/codex/companies").exists()


@pytest.mark.parametrize("damage", [False, True])
def test_publication_transfers_only_complete_configured_pdfs(config: Config, tmp_path: Path, damage: bool) -> None:
    """
    Verify every target before restoring any output and exclude incidental files from publication.

    Args:
        config (Config): Exact source configuration.
        tmp_path (Path): Source and destination checkout roots.
        damage (bool): Corrupt the second transferred PDF after staging.

    Returns:
        None: Complete variants restore atomically with respect to validation; damaged artifacts restore none.
    """
    source, destination, artifact = [tmp_path / name for name in ("source", "destination", "artifact")]
    paths = [company_config(config, target).output.pdf for target in config.codex.companies]

    for relative in paths:
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"%PDF-fixture\n" + relative.encode())

    stage_companies(source, config, artifact, generated=True)
    (artifact / "private.txt").write_text("unrelated runner state")

    if damage:
        (artifact / paths[1]).write_bytes(b"%PDF-corrupted")

        with pytest.raises(ValueError, match="verification"):
            restore_companies(destination, config, artifact)

        assert not destination.exists()
    else:
        assert restore_companies(destination, config, artifact) == paths
        assert all((destination / path).read_bytes() == (source / path).read_bytes() for path in paths)
        assert not (destination / "private.txt").exists()


def test_ci_matrix_and_response_artifact_keep_generic_plus_all_targets(
    profile: Profile, config: Config, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """
    Exercise CI preparation and per-item response staging using the same scripts as Actions.

    Args:
        profile (Profile): Source applicant.
        config (Config): Enabled targets with local evidence overrides.
        tmp_path (Path): Isolated CI checkout.
        monkeypatch (MonkeyPatch): Set trusted event flags and the selected matrix item.

    Returns:
        None: Generic and company entries share one consumer contract with distinct paths and artifact names.
    """
    scripts = Path(__file__).resolve().parents[3] / "scripts/ci"
    (tmp_path / "resumeme.config.yaml").write_text(yaml.safe_dump(asdict(config)))
    save_profile(profile, tmp_path / config.output.profile)
    output = tmp_path / "actions-output"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("GENERATE_SUMMARY", "true")
    monkeypatch.setenv("OPENAI_KEY_CONFIGURED", "true")
    runpy.run_path(str(scripts / "prepare-summary.py"))
    values = dict(line.split("=", 1) for line in output.read_text().splitlines())
    matrix = json.loads(values["matrix"])["include"]
    assert values["enabled"] == "true" and len(matrix) == 3
    assert matrix[0]["company"] == "" and len({item["key"] for item in matrix}) == 3
    _responses(tmp_path, profile, config)

    for item in matrix:
        monkeypatch.setenv("SUMMARY_COMPANY", item["company"])
        runpy.run_path(str(scripts / "summary-artifact.py"))

    result = tmp_path / ".cache/summary-result"
    assert (result / "summary.json").is_file()
    assert len(list(result.rglob("summary.json"))) == 3 and len(list(result.rglob("company.json"))) == 2
    assert not list(result.rglob("prompt.txt"))
