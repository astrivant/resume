"""
Verify tag-bound skill proposals and additive LinkedIn updates without model calls or live profile writes.
"""

from __future__ import annotations

import json
import runpy
import subprocess
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
import yaml
from attrs import evolve
from jsonschema import ValidationError
from selenium.common.exceptions import TimeoutException

from resumeme.cli import main
from resumeme.codex.skills import load_skill_suggestions, prepare_skills, skill_digest, skill_evidence, tag_revision
from resumeme.compiler.asts.profile import Entry, Profile, Section, Skill, save_profile
from resumeme.config import Capture, Codex, CodexSkills, Config, Experience, JobSelector, LinkedIn, load_config
from resumeme.linkedin.account import check_owner
from resumeme.linkedin.skills import _add_skill, _update_skills, publish_skills
from resumeme.tests.paths import REPOSITORY_ROOT

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch


@pytest.fixture
def tagged(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """
    Supply a disposable tagged checkout independent of the parent CI event.

    Args:
        tmp_path (Path): Temporary checkout directory.
        monkeypatch (MonkeyPatch): Scoped environment isolation.

    Returns:
        Path: Existing repository with resume-test at HEAD.
    """
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

    for arguments in (
        ["init", "--initial-branch=main"],
        ["config", "tag.gpgsign", "false"],
        [
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.org",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--allow-empty",
            "-m",
            "fixture",
        ],
        ["tag", "resume-test"],
    ):
        subprocess.run(["git", "-C", str(tmp_path), *arguments], check=True, capture_output=True)

    return tmp_path


def _config(*, publish: bool = False) -> Config:
    """
    Enable bounded suggestions without changing the independent summary settings.

    Args:
        publish (bool): Explicit live-update opt-in.

    Returns:
        Config: Owner settings with immediate retries for deterministic tests.
    """
    return Config(
        LinkedIn("example-person"),
        codex=Codex(skills=CodexSkills(enabled=True, publish=publish)),
        capture=Capture(retry_backoff_seconds=0),
    )


def _profile() -> Profile:
    """
    Supply demonstrated tools and an already endorsed skill.

    Returns:
        Profile: Minimal owner evidence with existing Python endorsements.
    """
    return Profile(
        "example-person",
        "Alex",
        sections=[
            Section("experience", "Experience", [Entry("Engineer", ["Built services with Python and Rust."])]),
            Section("skills", "Skills", [Entry("Python", skills=[Skill("Python", 7)])]),
            Section("contact", "Contact", [Entry("private@example.org")]),
        ],
    )


def _proposal(root: Path, profile: Profile, config: Config, skills: list[dict[str, str]]) -> Path:
    """
    Write a synthetic model response using the real evidence fingerprint.

    Args:
        root (Path): Tagged checkout and destination directory.
        profile (Profile): Input capture.
        config (Config): Generation settings.
        skills (list[dict[str, str]]): Candidate names and source quotes.

    Returns:
        Path: JSON proposal ready for validation.
    """
    evidence = skill_evidence(profile, config, "resume-test", tag_revision(root, "resume-test"))
    path = root / "skills.json"
    path.write_text(
        json.dumps({"username": profile.username, "source_tag": "resume-test", "source_digest": skill_digest(evidence), "skills": skills})
    )
    return path


def test_prompt_reuses_visibility_and_excludes_contact_and_employer_requirements(tagged: Path) -> None:
    """
    Derive proposals from retained professional evidence without exposing hidden profile content.

    Args:
        tagged (Path): Existing tagged checkout.

    Returns:
        None: Hidden jobs and contact data are absent and the response remains bound to its source.
    """
    profile = _profile()
    profile.sections[0].entries.append(Entry("Hidden role", ["UnlistedSkill work"]))
    config = evolve(_config(), experience=Experience(disable=[JobSelector(title="Hidden role")]))
    directory = prepare_skills(profile, config, tagged, "resume-test")
    prompt = (directory / "prompt.txt").read_text()
    assert "Python and Rust" in prompt
    assert "UnlistedSkill" not in prompt
    assert "private@example.org" not in prompt
    path = _proposal(tagged, profile, config, [{"name": "Rust", "evidence": "services with Python and Rust"}])
    assert load_skill_suggestions(path, profile, config, tagged, "resume-test").skills[0].name == "Rust"
    assert profile.sections[1].entries[0].skills == [Skill("Python", 7)]


def test_reasoning_change_invalidates_skill_proposal(tagged: Path) -> None:
    """
    Keep explicit reasoning settings in the proposal fingerprint without changing default evidence.

    Args:
        tagged (Path): Existing tagged checkout.

    Returns:
        None: Default evidence keeps its shape and a proposal cannot be reused with another reasoning level.
    """
    config, profile = _config(), _profile()
    assert "reasoning_effort" not in skill_evidence(profile, config, "resume-test", tag_revision(tagged, "resume-test"))
    path = _proposal(tagged, profile, config, [{"name": "Rust", "evidence": "Rust"}])
    changed = evolve(config, codex=evolve(config.codex, reasoning_effort="low"))

    with pytest.raises(ValueError):
        load_skill_suggestions(path, profile, changed, tagged, "resume-test")


@pytest.mark.parametrize(
    "skills",
    [
        [{"name": "Kubernetes", "evidence": "Built services with Python and Rust."}],
        [{"name": "Rust", "evidence": "Invented Rust expertise"}],
        [{"name": "Rust", "evidence": "Rust"}, {"name": "RUST", "evidence": "Rust"}],
        [{"name": " ", "evidence": "Rust"}],
    ],
)
def test_unsupported_or_duplicate_proposals_fail(tagged: Path, skills: list[dict[str, str]]) -> None:
    """
    Reject hallucinated evidence, unsupported names, and duplicate spellings before browser access.

    Args:
        tagged (Path): Existing tagged checkout.
        skills (list[dict[str, str]]): Invalid proposed skill records.

    Returns:
        None: Invalid candidates cannot be published.
    """
    config, profile = _config(), _profile()
    path = _proposal(tagged, profile, config, skills)

    with pytest.raises(ValueError):
        load_skill_suggestions(path, profile, config, tagged, "resume-test")


@pytest.mark.parametrize("field", ["username", "source_tag", "source_digest"])
def test_cross_owner_or_stale_proposals_fail(tagged: Path, field: str) -> None:
    """
    Require the proposal envelope to match the configured owner and exact generation input.

    Args:
        tagged (Path): Existing tagged checkout.
        field (str): Envelope field to alter.

    Returns:
        None: A mismatched envelope is rejected even with an empty proposal.
    """
    config, profile = _config(), _profile()
    path = _proposal(tagged, profile, config, [])
    raw = json.loads(path.read_text())
    raw[field] = "0" * 64 if field == "source_digest" else "other"
    path.write_text(json.dumps(raw))

    with pytest.raises(ValueError, match="owner, tag, or inputs"):
        load_skill_suggestions(path, profile, config, tagged, "resume-test")


def test_endorsement_fields_and_oversized_proposals_are_rejected(tagged: Path) -> None:
    """
    Keep generated skill declarations separate from endorsement records and configured cardinality.

    Args:
        tagged (Path): Existing tagged checkout.

    Returns:
        None: The model cannot supply counts or exceed the configured limit.
    """
    profile = _profile()
    config = evolve(_config(), codex=Codex(skills=CodexSkills(enabled=True, max_skills=1)))
    path = _proposal(tagged, profile, config, [{"name": name, "evidence": name} for name in ("Python", "Rust")])

    with pytest.raises(ValueError, match="max_skills"):
        load_skill_suggestions(path, profile, config, tagged, "resume-test")

    raw = json.loads(path.read_text())
    raw["skills"] = [{"name": "Python", "evidence": "Python", "endorsements": 99}]
    path.write_text(json.dumps(raw))

    with pytest.raises(ValidationError):
        load_skill_suggestions(path, profile, config, tagged, "resume-test")


@pytest.mark.parametrize(
    "event, reference", [("push", "refs/heads/main"), ("schedule", "refs/tags/resume-test"), ("pull_request", "refs/pull/1/merge")]
)
def test_non_tag_events_cannot_generate_or_publish(tagged: Path, monkeypatch: MonkeyPatch, event: str, reference: str) -> None:
    """
    Enforce tag-only behavior beneath the workflow's job conditions.

    Args:
        tagged (Path): Existing tagged checkout.
        monkeypatch (MonkeyPatch): Simulated Actions event environment.
        event (str): Disallowed event name.
        reference (str): Event ref, including a misleading tag ref on a scheduled run.

    Returns:
        None: No prompt or browser operation occurs for branch, scheduled, or pull-request events.
    """
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_EVENT_NAME", event)
    monkeypatch.setenv("GITHUB_REF", reference)

    with pytest.raises(ValueError, match="tag-push"):
        prepare_skills(_profile(), _config(), tagged, "resume-test")

    assert not (tagged / ".cache").exists()


def test_matching_annotated_tag_and_cli_prompt(tagged: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Resolve annotated tags correctly and expose prompt preparation through the installed command contract.

    Args:
        tagged (Path): Existing tagged checkout.
        monkeypatch (MonkeyPatch): Matching Actions tag event.

    Returns:
        None: The CLI prepares the schema at the expected artifact path.
    """
    subprocess.run(
        [
            "git",
            "-C",
            str(tagged),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.org",
            "tag",
            "-a",
            "annotated",
            "-m",
            "tag",
        ],
        check=True,
    )
    assert tag_revision(tagged, "annotated") == tag_revision(tagged, "resume-test")
    config = tagged / "resumeme.config.yaml"
    config.write_text("linkedin: {username: example-person}\ncodex: {skills: {enabled: true}}\n")
    save_profile(_profile(), tagged / "data/profile.json")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("GITHUB_REF", "refs/tags/resume-test")
    assert main(["--config", str(config), "skills-prompt", "--tag", "resume-test"]) == 0
    assert (tagged / ".cache/codex/skills/schema.json").exists()


def test_missing_tag_or_changed_checkout_rejects_proposals(tagged: Path) -> None:
    """
    Require a real tag at HEAD rather than accepting an arbitrary tag-shaped argument.

    Args:
        tagged (Path): Fixture repository with one initial tag.

    Returns:
        None: Missing tags and checkout/tag mismatches fail before preparing model inputs.
    """
    with pytest.raises(ValueError, match="existing Git tag"):
        tag_revision(tagged, "missing")

    subprocess.run(
        [
            "git",
            "-C",
            str(tagged),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.org",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--allow-empty",
            "-m",
            "later",
        ],
        check=True,
        capture_output=True,
    )

    with pytest.raises(ValueError, match="checked-out commit"):
        tag_revision(tagged, "resume-test")


def test_additions_preserve_endorsed_skills_and_reconcile_uncertain_saves(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Preserve existing names and endorsement totals while recognizing a Save that succeeded before a timeout.

    Args:
        tmp_path (Path): Ignored backup root.
        monkeypatch (MonkeyPatch): Deterministic live state and browser operations.

    Returns:
        None: Each missing skill is added once and previously endorsed skills remain untouched.
    """
    live = {"python": 7, "cloud computing": 42}
    additions: list[str] = []

    def save(driver: object, config: Config, name: str) -> None:
        """
        Simulate successful persistence followed by a lost browser response.

        Args:
            driver (object): Unused fake browser.
            config (Config): Unused validated settings.
            name (str): Requested new skill.

        Returns:
            None: The new skill persists before the simulated timeout.

        Raises:
            TimeoutException: The response was lost after Save.
        """
        additions.append(name)
        live[name.casefold()] = 0
        raise TimeoutException("lost Save response")

    monkeypatch.setattr("resumeme.linkedin.skills._current_skills", lambda *_: set(live))
    monkeypatch.setattr("resumeme.linkedin.skills._add_skill", save)
    assert _update_skills(MagicMock(), _config(), tmp_path, ["Python", "Rust"], dry_run=False) == ["Rust"]
    assert additions == ["Rust"]
    assert live == {"python": 7, "cloud computing": 42, "rust": 0}
    assert _update_skills(MagicMock(), _config(), tmp_path, ["Python", "Rust"], dry_run=False) == []
    assert additions == ["Rust"]


def test_preview_and_full_profile_never_save(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Preview additions and reject capacity overflow without dropping existing skills.

    Args:
        tmp_path (Path): Unused backup root.
        monkeypatch (MonkeyPatch): Controlled current skill list.

    Returns:
        None: Preview and a full profile never invoke the writer.
    """
    writer = MagicMock()
    monkeypatch.setattr("resumeme.linkedin.skills._add_skill", writer)
    monkeypatch.setattr("resumeme.linkedin.skills._current_skills", lambda *_: {"python"})
    assert _update_skills(MagicMock(), _config(), tmp_path, ["Python", "Rust"], dry_run=True) == ["Rust"]
    monkeypatch.setattr("resumeme.linkedin.skills._current_skills", lambda *_: {f"skill-{index}" for index in range(100)})

    with pytest.raises(ValueError, match="100-skill limit"):
        _update_skills(MagicMock(), _config(), tmp_path, ["Rust"], dry_run=False)

    writer.assert_not_called()
    assert not (tmp_path / ".cache").exists()


@pytest.mark.parametrize("lost_response", [False, True])
def test_unexpected_loss_stops_further_additions(tmp_path: Path, monkeypatch: MonkeyPatch, lost_response: bool) -> None:
    """
    Stop after a concurrent change removes an existing skill instead of continuing the batch.

    Args:
        tmp_path (Path): Backup root.
        monkeypatch (MonkeyPatch): Simulated server snapshots around Save.
        lost_response (bool): Whether Save times out before its state can be checked.

    Returns:
        None: No second addition or removal is attempted after the unexpected loss.
    """
    reader = MagicMock(side_effect=[{"python"}, {"python"}, {"rust"}])
    writer = MagicMock(side_effect=TimeoutException("lost Save response") if lost_response else None)
    monkeypatch.setattr("resumeme.linkedin.skills._current_skills", reader)
    monkeypatch.setattr("resumeme.linkedin.skills._add_skill", writer)

    with pytest.raises(ValueError, match="Existing LinkedIn skills changed"):
        _update_skills(MagicMock(), _config(), tmp_path, ["Rust", "Go"], dry_run=False)

    assert writer.call_count == 1


def test_publish_requires_opt_in_and_minimal_profiles_are_noops(tagged: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Keep live updates disabled unless configured, and allow a validated empty proposal without browser access.

    Args:
        tagged (Path): Tagged checkout.
        monkeypatch (MonkeyPatch): Browser creation sentinel.

    Returns:
        None: Neither missing opt-in nor an empty profile opens a browser.
    """
    browser = MagicMock()
    monkeypatch.setattr("resumeme.linkedin.skills._browser", browser)
    profile, config = Profile("example-person", "Alex"), _config(publish=True)
    save_profile(profile, tagged / config.output.profile)
    path = _proposal(tagged, profile, config, [])

    with pytest.raises(ValueError, match="opt in"):
        publish_skills(_config(), tagged, path, "resume-test")

    assert publish_skills(config, tagged, path, "resume-test", headless=True) == []
    browser.assert_not_called()


def test_add_form_selects_exact_skill_and_only_save(monkeypatch: MonkeyPatch) -> None:
    """
    Select the requested autocomplete entry without touching other skills, associations, or endorsements.

    Args:
        monkeypatch (MonkeyPatch): Browser navigation and dialog lifecycle fixtures.

    Returns:
        None: Exactly the matching option and Save are clicked.
    """
    driver, dialog, field, option, save, delete = (MagicMock() for _ in range(6))
    driver.current_url = "https://www.linkedin.com/in/example-person/edit/forms/skill/new/"
    option.text, save.text, delete.text = "Rust", "Save", "Delete"
    dialog.find_elements.side_effect = [[field], [save, delete]]
    driver.find_elements.side_effect = [[option], []]
    monkeypatch.setattr("resumeme.linkedin.skills._navigate", MagicMock())
    monkeypatch.setattr("resumeme.linkedin.skills._skill_dialog", lambda _: dialog)
    _add_skill(driver, _config(), "Rust")
    field.send_keys.assert_called_once_with("Rust")
    option.click.assert_called_once()
    save.click.assert_called_once()
    delete.click.assert_not_called()


def test_non_owner_profile_never_reaches_edit_route(monkeypatch: MonkeyPatch) -> None:
    """
    Require actual owner edit controls even when the browser can view the configured public profile.

    Args:
        monkeypatch (MonkeyPatch): Read-only navigation fixture.

    Returns:
        None: Missing edit controls fail before opening a skill editor.
    """
    driver = MagicMock()
    driver.current_url = "https://www.linkedin.com/in/example-person/"
    driver.find_elements.side_effect = [[MagicMock()], []]
    monkeypatch.setattr("resumeme.linkedin.account._navigate", MagicMock())

    with pytest.raises(ValueError, match="No owner edit control"):
        check_owner(driver, _config())


def test_ci_contract_is_tag_only_and_keeps_model_and_linkedin_credentials_separate() -> None:
    """
    Preserve release ordering, credential boundaries, and the shared LinkedIn write lock.

    Returns:
        None: Proposals run alongside summaries; live publication still requires a signed tag release and opt-in.
    """
    root = REPOSITORY_ROOT
    jobs = yaml.safe_load((root / ".github/workflows/ci.yml").read_text())["jobs"]
    caller = jobs["skills-stage"]
    publish_caller = jobs["skills-publish-stage"]
    workflow = yaml.safe_load((root / ".github/workflows/stage-skills.yml").read_text())["jobs"]
    publisher = yaml.safe_load((root / ".github/workflows/stage-skills-publish.yml").read_text())["jobs"]["publish"]
    assert caller["needs"] == ["source", "capture"]
    assert publish_caller["needs"] == ["source", "skills-stage", "release-stage"]
    assert "needs.skills-stage.result == 'success'" in publish_caller["if"]
    assert "needs.release-stage.result == 'success'" in publish_caller["if"]

    for job in (caller, publish_caller, workflow["generate"], publisher):
        assert "github.event_name == 'push'" in job["if"]
        assert "startsWith(github.ref, 'refs/tags/')" in job["if"]

    assert "publish == 'true'" in publish_caller["if"]
    assert publisher["concurrency"]["group"] == "resumeme-linkedin-ownership-${{ github.repository }}"
    assert "LINKEDIN_PASSWORD" not in json.dumps(caller)
    assert "OPENAI_API_KEY" not in json.dumps(publish_caller)
    assert "LINKEDIN_PASSWORD" not in json.dumps(workflow["generate"])
    assert "OPENAI_API_KEY" not in json.dumps(publisher)
    generator = next(step for step in workflow["generate"]["steps"] if step.get("uses", "").startswith("openai/codex-action@"))
    assert generator["with"]["effort"] == "${{ steps.settings.outputs.effort }}"


@pytest.mark.parametrize("effort", [None, "low"])
def test_ci_skill_preparation_exports_reasoning(tagged: Path, monkeypatch: MonkeyPatch, effort: str | None) -> None:
    """
    Pass configured model and reasoning settings from the tag's config to the upstream action.

    Args:
        tagged (Path): Fixture repository containing the selected tag.
        monkeypatch (MonkeyPatch): Scoped process arguments and trusted event state.
        effort (str | None): Explicit reasoning level or the CLI default.

    Returns:
        None: Preparation exports matching action inputs without receiving or using an API key.
    """
    script = REPOSITORY_ROOT / "scripts/ci/skills-artifact.py"
    (tagged / "resumeme.config.yaml").write_text(
        yaml.safe_dump(
            {
                "linkedin": {"username": "example-person"},
                "codex": {"model": "gpt-6-astra", "reasoning_effort": effort, "skills": {"enabled": True}},
            }
        )
    )
    save_profile(_profile(), tagged / "data/profile.json")
    output = tagged / "actions-output"
    monkeypatch.chdir(tagged)
    monkeypatch.setattr("sys.argv", [str(script), "prepare"])
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("GITHUB_REF", "refs/tags/resume-test")
    monkeypatch.setenv("RELEASE_TAG", "resume-test")
    monkeypatch.setenv("OPENAI_KEY_CONFIGURED", "true")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    runpy.run_path(str(script), run_name="__main__")
    assert "model=gpt-6-astra\n" in output.read_text()
    assert f"effort={effort or ''}\n" in output.read_text()
    assert (tagged / ".cache/codex/skills/prompt.txt").is_file()


def test_ci_script_rejects_branch_events(tagged: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Reject direct invocation of the artifact script outside tag events before preparing a prompt.

    Args:
        tagged (Path): Fixture repository and config root.
        monkeypatch (MonkeyPatch): Scoped process arguments and event state.

    Returns:
        None: A manually invoked branch build cannot prepare skill generation.
    """
    script = REPOSITORY_ROOT / "scripts/ci/skills-artifact.py"
    (tagged / "resumeme.config.yaml").write_text("linkedin: {username: example-person}\n")
    monkeypatch.chdir(tagged)
    monkeypatch.setattr("sys.argv", [str(script), "prepare"])
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("RELEASE_TAG", "resume-test")

    with pytest.raises(ValueError, match="tag-push"):
        runpy.run_path(str(script), run_name="__main__")


def test_publish_configuration_requires_generation(tmp_path: Path) -> None:
    """
    Require a proposal producer before accepting a publication opt-in.

    Args:
        tmp_path (Path): Temporary configuration directory.

    Returns:
        None: Defaults disable live writes and inconsistent opt-ins fail loading.
    """
    assert CodexSkills().publish is False
    path = tmp_path / "resumeme.config.yaml"
    path.write_text("linkedin: {username: example-person}\ncodex: {skills: {publish: true}}\n")

    with pytest.raises(ValueError, match="requires"):
        load_config(path)
