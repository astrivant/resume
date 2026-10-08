"""
Verify bounded Codex evidence, source binding, and offline summary rendering.
"""

from __future__ import annotations

import json
import runpy
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml
from attrs import evolve
from jsonschema import ValidationError

from resumeme.cli import main
from resumeme.codex.request import prepare_summary
from resumeme.compiler.asts.profile import Entry, Profile, Section, Skill, save_profile
from resumeme.compiler.asts.summary import load_summary
from resumeme.compiler.constants.sections import DEFAULT_SECTION_ORDER
from resumeme.compiler.passes.summary import summary_digest, summary_evidence
from resumeme.compiler.pipeline import render_profile
from resumeme.config import Codex, Config, Experience, JobSelector, LinkedIn, load_config

if TYPE_CHECKING:
    from pytest import CaptureFixture, MonkeyPatch


@pytest.fixture
def profile() -> Profile:
    """
    Supply captured copy, professional evidence, and an excluded role.

    Returns:
        Profile: Synthetic owner with replaceable About and headline values.
    """
    return Profile(
        "example-person",
        "Alex Example",
        intro=["Engineer at Example", "Example", "Boston, MA"],
        headline="Engineer at Example",
        sections=[
            Section("about", "About", [Entry("Original About")]),
            Section("experience", "Experience", [Entry("Engineer", ["Example", "2022 - Present", "Built services"])]),
            Section("contact", "Contact", [Entry("Private email", ["private@example.org"])]),
        ],
    )


def _summary_file(root: Path, profile: Profile, config: Config, **overrides: str) -> Path:
    """
    Write a structured model response bound to the supplied fixture.

    Args:
        root (Path): Temporary project directory.
        profile (Profile): Snapshot whose evidence the response describes.
        config (Config): Effective generation settings.
        **overrides (str): Fields replaced to exercise invalid and empty responses.

    Returns:
        Path: Explicit artifact consumed by rendering tests.
    """
    path = root / "summary.json"
    path.write_text(
        json.dumps(
            {
                "username": profile.username,
                "source_digest": summary_digest(profile, config),
                "about": "Builds reliable services for engineering teams.",
                "headline": "Platform engineer & systems builder",
                **overrides,
            }
        )
    )
    return path


def test_summary_updates_only_display_copy(profile: Profile, tmp_path: Path) -> None:
    """
    Overlay generated copy without restoring a captured headline or altering identity metadata.

    Args:
        profile (Profile): Captured fixture.
        tmp_path (Path): Temporary rendering directory.

    Returns:
        None: About and portrait copy render, the original snapshot and ordinary build stay intact.
    """
    config = Config(LinkedIn(profile.username), codex=Codex(enabled=True))
    summary = _summary_file(tmp_path, profile, config)
    source = render_profile(profile, config, tmp_path, summary_path=summary).read_text()
    document = source.split(r"\begin{document}", 1)[1]
    assert "Builds reliable services for engineering teams." in document
    assert r"Platform engineer \& systems builder" in document
    assert document.index(r"Platform engineer \& systems builder") < document.index(r"\companytext{Example}")
    assert "Original About" not in document and "Engineer at Example" not in document
    assert "Boston, MA" in document and "Built services" in document
    assert profile.headline == "Engineer at Example" and profile.sections[0].entries[0].title == "Original About"

    # Merely enabling the feature does not cause offline builds to discover stale files or contact a model.
    original = render_profile(profile, config, tmp_path).read_text()
    assert "Original About" in original and "Builds reliable services" not in original


def test_evidence_honors_exclusions_without_contact_data(profile: Profile) -> None:
    """
    Share compiler exclusions and remove contact details and Skills association prose from model inputs.

    Args:
        profile (Profile): Profile containing a visible professional role and contact block.

    Returns:
        None: Hidden role facts and disabled sections do not enter the prompt through reverse associations.
    """
    secret = Entry("Hidden role", ["Secret Company", "2020 - 2021", "Private project"])
    profile.sections[1].entries.append(secret)
    profile.sections.extend(
        [
            Section("skills", "Skills", [Entry("Python", ["Hidden role at Secret Company"], skills=[Skill("Python")])]),
            Section("recommendations", "Recommendations", [Entry("Secret recommendation")]),
        ]
    )
    config = Config(
        LinkedIn(profile.username),
        codex=Codex(enabled=True, context="Target platform engineering roles."),
        section_order=[key for key in DEFAULT_SECTION_ORDER if key not in (["recommendations"])],
        experience=Experience(disable=[JobSelector(title="Hidden role")]),
    )
    evidence = json.dumps(summary_evidence(profile, config))
    assert "Built services" in evidence and "Python" in evidence and "Target platform engineering" in evidence
    assert all(
        value not in evidence
        for value in ["Secret Company", "Hidden role", "Private project", "private@example.org", "Secret recommendation"]
    )


@pytest.mark.parametrize("change", ["owner", "context", "profile", "word_limit", "model", "effort", "disabled"])
def test_changed_inputs_reject_summary(profile: Profile, tmp_path: Path, change: str) -> None:
    """
    Reject cross-owner and stale responses even when their JSON remains structurally valid.

    Args:
        profile (Profile): Original summary evidence.
        tmp_path (Path): Summary artifact directory.
        change (str): Input changed after generation.

    Returns:
        None: Rendering fails before generated text can reach the document.
    """
    config = Config(LinkedIn(profile.username), codex=Codex(enabled=True))
    summary = _summary_file(tmp_path, profile, config)

    if change == "owner":
        profile = evolve(profile, username="someone-else")
    elif change == "profile":
        profile = evolve(profile, name="Changed name")
    elif change == "context":
        config = evolve(config, codex=evolve(config.codex, context="Changed target role"))
    elif change == "word_limit":
        config = evolve(config, codex=evolve(config.codex, about_max_words=50))
    elif change == "model":
        config = evolve(config, codex=evolve(config.codex, model="gpt-6-astra"))
    elif change == "effort":
        config = evolve(config, codex=evolve(config.codex, reasoning_effort="low"))
    else:
        config = evolve(config, codex=evolve(config.codex, enabled=False))

    with pytest.raises(ValueError):
        render_profile(profile, config, tmp_path, summary_path=summary)


@pytest.mark.parametrize("field", ["about", "headline"])
def test_word_limits_enforced_after_generation(profile: Profile, tmp_path: Path, field: str) -> None:
    """
    Enforce the configured word budget independently of model instructions.

    Args:
        profile (Profile): Source capture.
        tmp_path (Path): Artifact directory.
        field (str): Generated field exceeding its budget.

    Returns:
        None: Oversized output fails before rendering.
    """
    config = Config(LinkedIn(profile.username), codex=Codex(enabled=True))
    maximum = config.codex.about_max_words if field == "about" else config.codex.headline_max_words
    summary = _summary_file(tmp_path, profile, config, **{field: "word " * (maximum + 1)})

    with pytest.raises(ValueError, match="word limit"):
        load_summary(summary, username=profile.username, source_digest=summary_digest(profile, config), settings=config.codex)


def test_about_exclusion_and_empty_response(profile: Profile, tmp_path: Path) -> None:
    """
    Preserve section visibility and let minimal profiles return empty copy without fabrication.

    Args:
        profile (Profile): Source with an original About paragraph.
        tmp_path (Path): Temporary artifact directory.

    Returns:
        None: Hidden About stays absent and empty generated fields retain ordinary rendering.
    """
    config = Config(
        LinkedIn(profile.username),
        codex=Codex(enabled=True),
        section_order=[key for key in DEFAULT_SECTION_ORDER if key not in (["about"])],
    )
    summary = _summary_file(tmp_path, profile, config)
    source = render_profile(profile, config, tmp_path, summary_path=summary).read_text()
    assert r"\sectiontitle{About}" not in source and "Builds reliable services" not in source
    config = evolve(config, section_order=[key for key in DEFAULT_SECTION_ORDER if key not in ([])])
    summary = _summary_file(tmp_path, profile, config, about="", headline="")
    assert (
        render_profile(profile, config, tmp_path, summary_path=summary).read_text() == render_profile(profile, config, tmp_path).read_text()
    )

    minimal = Profile(profile.username, "Alex")
    summary = _summary_file(tmp_path, minimal, config, about="", headline="")
    assert r"\sectiontitle{About}" not in render_profile(minimal, config, tmp_path, summary_path=summary).read_text()


def test_prompt_and_cli_use_explicit_local_artifacts(profile: Profile, tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    """
    Prepare machine-readable inputs and render explicit summary output without credentials or live API access.

    Args:
        profile (Profile): Captured fixture.
        tmp_path (Path): Configuration directory.
        capsys (CaptureFixture[str]): Captures actionable CLI failure messages.

    Returns:
        None: Preparation preserves the snapshot and bad model JSON fails with a nonzero CLI exit.
    """
    config_path = tmp_path / "resumeme.config.yaml"
    config_path.write_text("linkedin:\n  username: example-person\ncodex:\n  enabled: true\n  context: Focus on platforms.\n")
    config = load_config(config_path)
    save_profile(profile, tmp_path / config.output.profile)
    before = (tmp_path / config.output.profile).read_bytes()
    assert main(["--config", str(config_path), "summary-prompt"]) == 0
    prompt = (tmp_path / ".cache/codex/prompt.txt").read_text()
    assert "Focus on platforms." in prompt and "private@example.org" not in prompt
    assert summary_digest(profile, config) in prompt
    assert json.loads((tmp_path / ".cache/codex/schema.json").read_text())["additionalProperties"] is False
    assert (tmp_path / config.output.profile).read_bytes() == before
    _summary_file(tmp_path, profile, config)
    assert main(["--config", str(config_path), "render", "--summary", "summary.json"]) == 0
    (tmp_path / "summary.json").write_text('{"about":"Missing required fields"}')
    assert main(["--config", str(config_path), "render", "--summary", "summary.json"]) == 2
    captured = capsys.readouterr()
    assert "required property" in captured.out
    assert captured.err == ""


@pytest.mark.parametrize(
    "override",
    [
        {"api_key": "not-allowed"},
        {"about_max_words": 0},
        {"headline_max_words": 41},
        {"model": "bad\nmodel"},
        {"reasoning_effort": "light"},
        {"reasoning_effort": "low\nmodel=other"},
        {"reasoning_effort": False},
    ],
)
def test_codex_config_rejects_credentials_and_invalid_limits(tmp_path: Path, override: dict[str, object]) -> None:
    """
    Keep credentials outside config and validate generation settings before CI starts.

    Args:
        tmp_path (Path): Configuration directory.
        override (dict[str, object]): Invalid Codex settings.

    Returns:
        None: Strict schema validation rejects unknown keys, invalid models, and word budgets.
    """
    config = tmp_path / "resumeme.config.yaml"
    config.write_text(yaml.safe_dump({"linkedin": {"username": "example-person"}, "codex": override}))

    with pytest.raises(ValidationError):
        load_config(config)


@pytest.mark.parametrize("effort", [None, "none", "minimal", "low", "medium", "high", "xhigh", "max"])
def test_codex_reasoning_effort_configuration(tmp_path: Path, effort: str | None) -> None:
    """
    Load reasoning independently of the model while preserving CLI defaults when omitted.

    Args:
        tmp_path (Path): Isolated configuration directory.
        effort (str | None): Supported CLI effort value or an explicit default.

    Returns:
        None: The selected level survives schema validation and typed configuration loading.
    """
    path = tmp_path / "resumeme.config.yaml"
    path.write_text(
        yaml.safe_dump({"linkedin": {"username": "example-person"}, "codex": {"model": "gpt-6-astra", "reasoning_effort": effort}})
    )
    config = load_config(path)
    assert config.codex.model == "gpt-6-astra"
    assert config.codex.reasoning_effort == effort
    assert Codex().reasoning_effort is None


def test_prepare_requires_enabled_complete_source(profile: Profile, tmp_path: Path) -> None:
    """
    Avoid summarizing incomplete captures or accidentally enabling model-backed work.

    Args:
        profile (Profile): Valid source capture.
        tmp_path (Path): Request directory.

    Returns:
        None: Invalid requests fail before any prompt is written.
    """
    config = Config(LinkedIn(profile.username))

    with pytest.raises(ValueError, match="enabled"):
        prepare_summary(profile, config, tmp_path)

    with pytest.raises(ValueError, match="warnings"):
        prepare_summary(evolve(profile, warnings=["Incomplete capture"]), evolve(config, codex=Codex(enabled=True)), tmp_path)


def test_ci_shares_one_summary_without_key_exposure() -> None:
    """
    Verify the reusable workflow contract keeps one artifact across checks and the PDF build.

    Returns:
        None: Both consumers depend on generation, while the API key remains in the trusted summary job.
    """
    workflows = Path(__file__).resolve().parents[3] / ".github/workflows"
    pipeline = yaml.safe_load((workflows / "ci.yml").read_text())
    stage = (workflows / "stage-summary.yml").read_text()
    assert "github.ref == 'refs/heads/main' && github.event_name != 'pull_request'" in stage
    assert "permission-profile: ':read-only'" in stage and "safety-strategy: drop-sudo" in stage
    assert "OPENAI_API_KEY:" not in stage.split("jobs:", 1)[1]
    jobs = yaml.safe_load(stage)["jobs"]
    assert jobs["prepare"]["outputs"]["matrix"] == "${{ steps.prepare.outputs.matrix }}"
    generator = next(step for step in jobs["summary"]["steps"] if step.get("uses", "").startswith("openai/codex-action@"))
    assert generator["with"]["effort"] == "${{ matrix.effort }}"
    assert generator["with"]["model"] == "${{ matrix.model }}"

    for name in ["test", "build"]:
        job = pipeline["jobs"][f"{name}-stage"]
        assert "summary-stage" in job["needs"]
        assert "generated" in job["with"]["summary"]
        consumer = (workflows / f"stage-{name}.yml").read_text()
        assert "name: resumeme-summary" in consumer and "USE_CODEX_SUMMARY:" in consumer
        assert "OPENAI_API_KEY" not in consumer


@pytest.mark.parametrize(
    "enabled,trusted,key_present", [(False, True, False), (True, False, False), (True, True, False), (True, True, True)]
)
@pytest.mark.parametrize("effort", [None, "low"])
def test_ci_preparation_requires_opt_in_trust_and_key(
    profile: Profile, tmp_path: Path, monkeypatch: MonkeyPatch, enabled: bool, trusted: bool, key_present: bool, effort: str | None
) -> None:
    """
    Exercise the actual setup script across disabled, untrusted, missing-key, and enabled CI paths.

    Args:
        profile (Profile): Source capture for the trusted generation case.
        tmp_path (Path): Temporary checkout with an Actions output file.
        monkeypatch (MonkeyPatch): Controls the workflow's boolean environment and working directory.
        enabled (bool): Whether local configuration opts into generation.
        trusted (bool): Whether the workflow selected a trusted main-branch event.
        key_present (bool): Presence flag without access to the secret itself.
        effort (str | None): Optional reasoning override passed to every summary matrix item.

    Returns:
        None: Only fully configured trusted runs produce a prompt; missing credentials fail explicitly.
    """
    script = Path(__file__).resolve().parents[3] / "scripts/ci/prepare-summary.py"
    config = tmp_path / "resumeme.config.yaml"
    config.write_text(
        yaml.safe_dump(
            {"linkedin": {"username": profile.username}, "codex": {"enabled": enabled, "model": "gpt-6-astra", "reasoning_effort": effort}}
        )
    )
    save_profile(profile, tmp_path / "data/profile.json")
    output = tmp_path / "actions-output"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("GENERATE_SUMMARY", str(trusted).lower())
    monkeypatch.setenv("OPENAI_KEY_CONFIGURED", str(key_present).lower())

    if enabled and trusted and not key_present:
        with pytest.raises(ValueError, match="OPENAI_API_KEY repository secret"):
            runpy.run_path(str(script))

        assert not (tmp_path / ".cache/codex/prompt.txt").exists()
        return

    runpy.run_path(str(script))
    assert f"enabled={str(enabled and trusted).lower()}" in output.read_text()
    values = dict(line.split("=", 1) for line in output.read_text().splitlines())
    generic = json.loads(values["matrix"])["include"][0]
    assert generic["model"] == "gpt-6-astra" and generic["effort"] == (effort or "")
    assert (tmp_path / ".cache/codex/prompt.txt").is_file() is (enabled and trusted)
