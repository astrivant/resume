"""
Verify saved-resume publication without signing in or uploading personal files to LinkedIn.
"""

from __future__ import annotations

import os
import runpy
import subprocess
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
import yaml
from attrs import evolve
from jsonschema import ValidationError
from pypdf import PdfWriter
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By

from resumeme.cli import main
from resumeme.compiler.asts.profile import Profile, save_profile
from resumeme.config import Capture, Config, LinkedIn, LinkedInResume, load_config
from resumeme.exceptions import BrowserError
from resumeme.linkedin.resume import (
    _delete_saved_resume,
    _pdf_bytes,
    _replace_existing_resumes,
    _resume_action,
    _resume_filename,
    _saved,
    _saved_resume_names,
    _send_pdf_file,
    _upload_input,
    _upload_resume,
    publish_resume,
)
from resumeme.tests.paths import REPOSITORY_ROOT

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch


def _config(*, replace_existing: bool = False) -> Config:
    """
    Provide an opted-in account with immediate deterministic browser waits.

    Args:
        replace_existing (bool): Whether the test account opts in to deleting older saved resumes.

    Returns:
        Config: Test-only timing policy and explicitly enabled upload.
    """
    return Config(
        linkedin=LinkedIn(username="example-person", resume=LinkedInResume(publish=True, replace_existing=replace_existing)),
        capture=Capture(page_timeout_seconds=0, retry_attempts=3, retry_backoff_seconds=0),
    )


@pytest.fixture
def pdf(tmp_path: Path) -> Path:
    """
    Create a real parseable PDF independent of the repository's personal resume.

    Args:
        tmp_path (Path): Disposable document directory.

    Returns:
        Path: One-page unencrypted PDF.
    """
    path = tmp_path / "release.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(path)
    return path


@pytest.mark.parametrize("setting", [None, False, True])
def test_config_and_ci_gate_share_explicit_opt_in(setting: bool | None, tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Keep absent configuration disabled and expose exactly the loaded opt-in to Actions.

    Args:
        setting (bool | None): Omitted, disabled, or enabled publication setting.
        tmp_path (Path): Minimal fork configuration and Actions output file.
        monkeypatch (MonkeyPatch): Scoped script working directory and output environment.

    Returns:
        None: Configuration and the real workflow settings script agree.
    """
    script = REPOSITORY_ROOT / "scripts/ci/resume-settings.py"
    config = tmp_path / "resumeme.config.yaml"
    config.write_text("linkedin:\n  username: example-person\n" + ("" if setting is None else f"  resume:\n    publish: {setting}\n"))
    assert load_config(config).linkedin.resume.publish is (setting is True)
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.chdir(tmp_path)
    runpy.run_path(str(script))
    assert output.read_text() == f"enabled={str(setting is True).lower()}\n"


@pytest.mark.parametrize(
    "resume",
    [{"publish": "true"}, {"publish": 1}, {"replace_existing": "true"}, {"replace_existing": 1}, {"sharing": True}],
)
def test_invalid_upload_config_is_rejected(resume: dict[str, str | int | bool], tmp_path: Path) -> None:
    """
    Reject ambiguous opt-in values and unsupported privacy switches.

    Args:
        resume (dict[str, str | int | bool]): Invalid upload configuration.
        tmp_path (Path): Isolated configuration directory.

    Returns:
        None: Validation fails instead of coercing publication intent.
    """
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({"linkedin": {"username": "example-person", "resume": resume}}))

    with pytest.raises(ValidationError):
        load_config(config)


def test_disabled_publisher_never_reads_pdf_or_opens_browser(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Stop before local file access and credential checks when live upload is disabled.

    Args:
        tmp_path (Path): Directory without a PDF.
        monkeypatch (MonkeyPatch): Browser invocation recorder.

    Returns:
        None: The explicit opt-in error precedes every publication side effect.
    """
    browser = MagicMock()
    monkeypatch.setattr("resumeme.linkedin.resume._browser", browser)

    with pytest.raises(BrowserError, match=r"linkedin.resume.publish: true"):
        publish_resume(Config(linkedin=LinkedIn(username="example-person")), tmp_path, tmp_path / "missing.pdf", headless=True)

    browser.assert_not_called()
    assert not (tmp_path / ".cache").exists()


@pytest.mark.parametrize("kind", ["html", "broken", "empty", "encrypted"])
def test_invalid_pdfs_fail_before_browser(kind: str, pdf: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Require real unencrypted pages rather than trusting a filename extension.

    Args:
        kind (str): Unsupported or malformed input variant.
        pdf (Path): Input path replaced by the selected invalid document.
        monkeypatch (MonkeyPatch): Browser call recorder.

    Returns:
        None: Invalid PDFs never reach LinkedIn.
    """
    writer = PdfWriter()

    if kind == "encrypted":
        writer.add_blank_page(width=612, height=792)
        writer.encrypt("test-only-password")

    writer.write(pdf)

    if kind in {"html", "broken"}:
        pdf.write_bytes(b"<html>not a PDF</html>" if kind == "html" else b"%PDF-1.7\nbroken")

    browser = MagicMock()
    monkeypatch.setattr("resumeme.linkedin.resume._browser", browser)

    with pytest.raises(BrowserError):
        publish_resume(_config(), pdf.parent, pdf)

    browser.assert_not_called()


@pytest.mark.parametrize("dry_run", [False, True])
def test_staged_upload_preserves_exact_release_bytes(dry_run: bool, pdf: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Bind retry identity to the signed bytes and clean private staging after publication or preview.

    Args:
        dry_run (bool): Live upload or a permitted preview with publication disabled.
        pdf (Path): Valid release fixture.
        monkeypatch (MonkeyPatch): Replace authentication and browser boundaries.

    Returns:
        None: Staged and original bytes match, the filename is stable, and scratch data is removed.
    """
    content = pdf.read_bytes()
    expected = _resume_filename("Example Person", content)
    staged_paths: list[Path] = []

    def record_upload(driver: object, config: Config, selected: Path, *, dry_run: bool) -> str:
        """
        Inspect the actual temporary file at the upload boundary.

        Args:
            driver (object): Browser context mock.
            config (Config): Loaded owner and opt-in.
            selected (Path): Immutable copy selected for the browser.
            dry_run (bool): Requested preview mode.

        Returns:
            str: Proposed or confirmed upload filename.
        """
        assert selected.read_bytes() == content
        assert selected.name == expected
        assert selected.parent.stat().st_mode & 0o777 == 0o700
        staged_paths.append(selected)
        return selected.name

    config = _config()

    if dry_run:
        config = evolve(config, linkedin=evolve(config.linkedin, resume=LinkedInResume()))

    for name in ("_browser", "_login", "_navigate", "login_credentials"):
        monkeypatch.setattr(f"resumeme.linkedin.resume.{name}", MagicMock())

    monkeypatch.setattr("resumeme.linkedin.resume._upload_resume", record_upload)

    for _ in range(2):
        assert publish_resume(config, pdf.parent, pdf, profile_name="Example Person", dry_run=dry_run) == expected

    assert len(staged_paths) == 2
    assert all(not selected.exists() for selected in staged_paths)
    assert _pdf_bytes(pdf) == content


def test_upload_filename_uses_profile_name_and_preserves_content_identity() -> None:
    """
    Produce a readable ASCII owner filename with a stable digest of the signed document.

    Returns:
        None: Names normalize consistently and different PDF bytes produce different filenames.
    """
    content = b"signed resume bytes"

    assert _resume_filename("Émma Doyle", content).startswith("emma-doyle-resume-")
    assert _resume_filename("Émma Doyle", content).endswith(".pdf")
    assert _resume_filename("Émma Doyle", content) != _resume_filename("Émma Doyle", content + b" update")


def test_resume_replacement_defaults_to_opt_out_in_reference_and_opt_in_for_author() -> None:
    """
    Keep fork defaults conservative while allowing this project's personal config to replace older files.

    Returns:
        None: Package and reference defaults retain old resumes; the checked-in personal setting enables replacement.
    """
    root = REPOSITORY_ROOT

    assert not LinkedInResume().replace_existing
    assert not load_config(root / "resumeme.config.ref.yaml").linkedin.resume.replace_existing
    assert load_config(root / "resumeme.config.yaml").linkedin.resume.replace_existing


@pytest.mark.parametrize("replace_existing,dry_run", [(True, False), (True, True), (False, False)])
def test_replacement_runs_only_after_confirmed_upload_and_never_in_preview(
    replace_existing: bool, dry_run: bool, pdf: Path, monkeypatch: MonkeyPatch
) -> None:
    """
    Delete older resumes only after upload reconciliation, and never during dry runs.

    Args:
        replace_existing (bool): Whether the account config opted in to replacement.
        dry_run (bool): Whether the command only previews LinkedIn changes.
        pdf (Path): Valid release fixture.
        monkeypatch (MonkeyPatch): Replace browser operations with ordered boundary recorders.

    Returns:
        None: Replacement follows confirmation exactly when enabled and live.
    """
    events: list[str] = []
    config = _config(replace_existing=replace_existing)

    for name in ("_browser", "_login", "_navigate", "login_credentials"):
        monkeypatch.setattr(f"resumeme.linkedin.resume.{name}", MagicMock())

    def upload(_driver: object, _config: Config, _selected: Path, *, dry_run: bool) -> str:
        """
        Record that the new PDF has passed the upload confirmation boundary.

        Args:
            _driver (object): Test browser placeholder.
            _config (Config): Loaded owner and replacement settings.
            _selected (Path): Private staged release file.
            dry_run (bool): Whether publication is only being previewed.

        Returns:
            str: Fixture filename returned by the publisher.
        """
        events.append("upload")
        return pdf.name

    monkeypatch.setattr("resumeme.linkedin.resume._upload_resume", MagicMock(side_effect=upload))
    replacement = MagicMock(side_effect=lambda *_args: events.append("replace"))
    monkeypatch.setattr("resumeme.linkedin.resume._replace_existing_resumes", replacement)
    monkeypatch.setattr(
        "resumeme.linkedin.resume._recruiter_sharing", MagicMock(side_effect=lambda *_args, **_kwargs: events.append("sharing"))
    )

    publish_resume(config, pdf.parent, pdf, profile_name="Example Person", dry_run=dry_run)

    assert events[0] == "upload"
    assert ("replace" in events) is (replace_existing and not dry_run)
    assert events.index("sharing") > events.index("upload")
    if "replace" in events:
        assert events.index("replace") < events.index("sharing")


def test_replace_existing_resumes_preserves_new_file_and_removes_all_others(monkeypatch: MonkeyPatch) -> None:
    """
    Reconcile the list until only the current verified file remains.

    Args:
        monkeypatch (MonkeyPatch): Model LinkedIn's saved list and confirmed delete operations.

    Returns:
        None: Every prior filename is removed, while the new release is retained.
    """
    saved = {"current-release.pdf", "old-one.pdf", "old-two.pdf"}
    deleted: list[str] = []
    monkeypatch.setattr("resumeme.linkedin.resume._settings", MagicMock())
    monkeypatch.setattr("resumeme.linkedin.resume._saved_resume_names", lambda _driver: set(saved))

    def delete(_driver: object, _config: Config, filename: str) -> None:
        """
        Apply a confirmed deletion to the in-memory server state.

        Args:
            _driver (object): Test browser placeholder.
            _config (Config): Test retry settings.
            filename (str): Saved resume selected by the replacement loop.

        Returns:
            None: The selected old resume is removed from the simulated account.
        """
        deleted.append(filename)
        saved.remove(filename)

    monkeypatch.setattr("resumeme.linkedin.resume._delete_saved_resume", delete)
    _replace_existing_resumes(MagicMock(), _config(), "current-release.pdf")

    assert saved == {"current-release.pdf"}
    assert deleted == ["old-one.pdf", "old-two.pdf"]


def test_replace_existing_fails_closed_when_new_release_is_not_visible(monkeypatch: MonkeyPatch) -> None:
    """
    Keep old resumes untouched if LinkedIn's saved list no longer shows the new release.

    Args:
        monkeypatch (MonkeyPatch): Model a stale or incomplete saved-resume list.

    Returns:
        None: A missing current release prevents all deletion attempts.
    """
    deletion = MagicMock()
    monkeypatch.setattr("resumeme.linkedin.resume._settings", MagicMock())
    monkeypatch.setattr("resumeme.linkedin.resume._saved_resume_names", lambda _driver: {"old.pdf"})
    monkeypatch.setattr("resumeme.linkedin.resume._delete_saved_resume", deletion)

    with pytest.raises(BrowserError, match="no previous resume was deleted"):
        _replace_existing_resumes(MagicMock(), _config(), "current-release.pdf")

    deletion.assert_not_called()


def test_saved_resume_names_ignore_non_filename_text() -> None:
    """
    Count only visible full PDF filenames when deciding which saved documents to remove.

    Returns:
        None: Explanatory text, hidden names, and notices are not treated as resumes.
    """
    driver = MagicMock()
    filename, explanation, hidden = MagicMock(), MagicMock(), MagicMock()
    filename.text = "Résumé, Emma's file (2025).pdf"
    filename.is_displayed.return_value = True
    explanation.text = "Upload a PDF resume to apply"
    explanation.is_displayed.return_value = True
    hidden.text = "old-resume.pdf"
    hidden.is_displayed.return_value = False
    driver.find_elements.side_effect = [[], [filename, explanation, hidden]]

    assert _saved_resume_names(driver) == {"Résumé, Emma's file (2025).pdf"}


def test_resume_action_is_bound_to_filename_row() -> None:
    """
    Select the overflow menu on the exact filename row instead of a page-level action.

    Returns:
        None: The returned control is associated with only the requested saved file.
    """
    driver, label, row, menu = MagicMock(), MagicMock(), MagicMock(), MagicMock()
    row.text = "old-resume.pdf"
    menu.id = "resume-menu"
    menu.is_displayed.return_value = True
    menu.is_enabled.return_value = True
    menu.get_attribute.side_effect = {"aria-label": "More options", "title": None}.get
    menu.text = ""
    label.is_displayed.return_value = True
    label.find_element.return_value = row
    row.find_elements.return_value = [menu]
    driver.find_elements.return_value = [label]

    assert _resume_action(driver, "old-resume.pdf", {"old-resume.pdf", "current.pdf"}) == (menu, True)


def test_saved_resume_delete_confirms_menu_action_and_server_removal(monkeypatch: MonkeyPatch) -> None:
    """
    Submit a row-scoped Delete action once and verify the file disappears after navigation.

    Args:
        monkeypatch (MonkeyPatch): Replace LinkedIn reads and controls with deterministic observations.

    Returns:
        None: The menu, confirmation, and persisted removal are each observed once.
    """
    events: list[str] = []
    menu = MagicMock()
    confirmation = MagicMock()
    driver = MagicMock()
    monkeypatch.setattr("resumeme.linkedin.resume._settings", MagicMock(side_effect=lambda *_args: events.append("settings")))
    monkeypatch.setattr("resumeme.linkedin.resume._saved_resume_names", MagicMock(side_effect=[{"old.pdf"}, set()]))
    monkeypatch.setattr("resumeme.linkedin.resume._resume_action", MagicMock(return_value=(menu, True)))
    menu_item = MagicMock()
    menu_item.click.side_effect = lambda: events.append("delete")
    monkeypatch.setattr("resumeme.linkedin.resume._delete_menu_item", MagicMock(return_value=menu_item))
    confirmation.click.side_effect = lambda: events.append("confirm")
    monkeypatch.setattr("resumeme.linkedin.resume._delete_confirmation", MagicMock(return_value=confirmation))

    _delete_saved_resume(driver, _config(), "old.pdf")

    menu.click.assert_called_once_with()
    menu_item.click.assert_called_once_with()
    confirmation.click.assert_called_once_with()
    assert events == ["settings", "delete", "confirm", "settings"]


@pytest.mark.parametrize(
    "url",
    [
        "https://www.linkedin.com/login",
        "https://www.linkedin.com.evil.example/jobs/application-settings/",
        "http://www.linkedin.com/jobs/application-settings/",
    ],
)
def test_unexpected_upload_destination_fails_closed(url: str) -> None:
    """
    Reject login challenges and changed origins before considering any file inputs.

    Args:
        url (str): Unexpected browser destination.

    Returns:
        None: No upload field is selected.
    """
    driver = MagicMock(current_url=url)

    with pytest.raises(BrowserError, match="left its application settings"):
        _upload_input(driver)

    driver.find_elements.assert_not_called()


@pytest.mark.parametrize("path", ["/jobs/application-settings/", "/jobs/preferences/application-preferences/"])
def test_pdf_input_selection_ignores_unrelated_uploads(path: str) -> None:
    """
    Support both documented settings routes and hidden PDF inputs without clicking desktop dialogs.

    Args:
        path (str): LinkedIn's original or current preferences route.

    Returns:
        None: Only the enabled PDF input is selected; ambiguity fails closed.
    """
    driver = MagicMock(current_url=f"https://www.linkedin.com{path}")
    photo, resume = MagicMock(), MagicMock()
    photo.get_attribute.return_value = "image/*"
    resume.get_attribute.return_value = ".doc, .docx, application/pdf"
    resume.is_displayed.return_value = False
    driver.find_elements.side_effect = [[], [photo, resume], [], [resume, resume]]
    assert _upload_input(driver) is resume
    resume.click.assert_not_called()

    with pytest.raises(BrowserError, match="multiple"):
        _upload_input(driver)


def test_loading_settings_does_not_offer_an_upload_input() -> None:
    """
    Wait for saved resumes before deciding whether an upload would duplicate existing content.

    Returns:
        None: A busy settings page cannot expose an upload input to the publisher.
    """
    driver = MagicMock(current_url="https://www.linkedin.com/jobs/application-settings/")
    driver.find_elements.return_value = [MagicMock()]
    assert _upload_input(driver) is False
    assert driver.find_elements.call_count == 1


def test_hidden_pdf_input_is_exposed_only_while_selecting_the_file(pdf: Path) -> None:
    """
    Handle LinkedIn's display-none file control while preserving its page styling afterward.

    Args:
        pdf (Path): Staged document selected by the browser.

    Returns:
        None: Selenium selects the exact file and the input's original attributes are restored.
    """
    driver, field = MagicMock(), MagicMock()
    field.is_displayed.return_value = False
    field.get_attribute.side_effect = {"class": "hidden", "style": None}.get

    _send_pdf_file(driver, field, pdf)

    field.send_keys.assert_called_once_with(str(pdf.resolve()))
    assert driver.execute_script.call_count == 2
    expose_script = driver.execute_script.call_args_list[0].args[0]
    restore_call = driver.execute_script.call_args_list[1]
    assert "classList.remove('hidden')" in expose_script
    assert restore_call.args[2:] == ("hidden", None)


def test_saved_detection_waits_for_progress_and_ignores_hidden_names() -> None:
    """
    Avoid accepting pending upload names or invisible stale cards as saved resumes.

    Returns:
        None: Only a visible completed filename can satisfy the saved check.
    """
    driver = MagicMock()
    progress, name = MagicMock(), MagicMock()
    driver.find_elements.return_value = [progress]
    assert not _saved(driver, "resume-0123456789abcdef.pdf")
    name.is_displayed.return_value = False
    driver.find_elements.side_effect = [[], [name]]
    assert not _saved(driver, "resume-0123456789abcdef.pdf")
    name.is_displayed.return_value = True
    driver.find_elements.side_effect = [[], [name]]
    assert _saved(driver, "resume-0123456789abcdef.pdf")
    by, selector = driver.find_elements.call_args.args
    assert by == By.XPATH
    assert "normalize-space(.)='resume-0123456789abcdef.pdf'" in selector
    assert "@role='alert'" in selector


@pytest.mark.parametrize("already_saved,dry_run", [(True, False), (False, True)])
def test_existing_resume_and_dry_run_never_upload(already_saved: bool, dry_run: bool, pdf: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Avoid duplicate uploads on retries and avoid all writes during previews.

    Args:
        already_saved (bool): Whether fresh server state contains this exact content filename.
        dry_run (bool): Whether the caller only requested an upload preview.
        pdf (Path): Selected release fixture.
        monkeypatch (MonkeyPatch): Replace the account and settings read boundaries.

    Returns:
        None: No file selection or button click occurs.
    """
    driver, field = MagicMock(), MagicMock()
    monkeypatch.setattr("resumeme.linkedin.resume.check_owner", MagicMock())
    monkeypatch.setattr("resumeme.linkedin.resume._settings", MagicMock(return_value=field))
    monkeypatch.setattr("resumeme.linkedin.resume._saved", MagicMock(return_value=already_saved))
    assert _upload_resume(driver, _config(), pdf, dry_run=dry_run) == pdf.name
    field.send_keys.assert_not_called()
    driver.execute_script.assert_not_called()
    field.click.assert_not_called()


@pytest.mark.parametrize("uncertain", [False, True])
def test_upload_is_confirmed_after_fresh_navigation(uncertain: bool, pdf: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Recognize a persisted upload even when its WebDriver response was lost.

    Args:
        uncertain (bool): Whether file selection raises after the server accepted the document.
        pdf (Path): Selected release fixture.
        monkeypatch (MonkeyPatch): Deterministic server observations and read retries.

    Returns:
        None: One upload occurs, followed by fresh reads that eventually confirm persistence.
    """
    driver, field = MagicMock(), MagicMock()

    if uncertain:
        field.send_keys.side_effect = TimeoutException()

    settings = MagicMock(return_value=field)
    monkeypatch.setattr("resumeme.linkedin.resume.check_owner", MagicMock())
    monkeypatch.setattr("resumeme.linkedin.resume._settings", settings)
    monkeypatch.setattr("resumeme.linkedin.resume._saved", MagicMock(side_effect=[False] + ([] if uncertain else [True]) + [False, True]))
    assert _upload_resume(driver, _config(), pdf, dry_run=False) == pdf.name
    field.send_keys.assert_called_once_with(str(pdf.resolve()))
    assert settings.call_count == 3


def test_local_filename_without_server_persistence_fails(pdf: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Reject a completed-looking local upload form when fresh settings never show the file.

    Args:
        pdf (Path): Selected release fixture.
        monkeypatch (MonkeyPatch): Deterministic local success followed by absent server state.

    Returns:
        None: Exhausted read retries fail visibly without resubmitting the document.
    """
    field = MagicMock()
    monkeypatch.setattr("resumeme.linkedin.resume.check_owner", MagicMock())
    monkeypatch.setattr("resumeme.linkedin.resume._settings", MagicMock(return_value=field))
    monkeypatch.setattr("resumeme.linkedin.resume._saved", MagicMock(side_effect=[False, True, False, False, False]))

    with pytest.raises(BrowserError, match="No second upload was submitted"):
        _upload_resume(MagicMock(), _config(), pdf, dry_run=False)

    field.send_keys.assert_called_once()


def test_wrong_owner_prevents_settings_and_upload(pdf: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Retain the shared account ownership guard before visiting upload settings.

    Args:
        pdf (Path): Selected release fixture.
        monkeypatch (MonkeyPatch): Reject account ownership at the read boundary.

    Returns:
        None: Upload settings are never reached for another account.
    """
    settings = MagicMock()
    monkeypatch.setattr("resumeme.linkedin.resume.check_owner", MagicMock(side_effect=BrowserError("Not the owner")))
    monkeypatch.setattr("resumeme.linkedin.resume._settings", settings)

    with pytest.raises(BrowserError, match="Not the owner"):
        _upload_resume(MagicMock(), _config(), pdf, dry_run=False)

    settings.assert_not_called()


def test_cli_resolves_explicit_pdf_without_snapshot(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Support local recovery from a downloaded release without loading a captured profile.

    Args:
        tmp_path (Path): Configuration outside the current working directory.
        monkeypatch (MonkeyPatch): Publication boundary recorder.

    Returns:
        None: CLI flags and the configuration-relative PDF reach the publisher unchanged.
    """
    config = tmp_path / "resumeme.config.yaml"
    config.write_text("linkedin: {username: example-person}\n")
    publisher = MagicMock(return_value="resume-fixture.pdf")
    monkeypatch.setattr("resumeme.cli.publish_resume", publisher)
    assert main(["--config", str(config), "publish-resume", "--pdf", "signed/resume.pdf", "--dry-run", "--headless"]) == 0
    args, kwargs = publisher.call_args
    assert args[1:] == (tmp_path, tmp_path / "signed/resume.pdf")
    assert kwargs == {"profile_name": "example-person", "dry_run": True, "headless": True, "connect_port": None}


def test_cli_uses_captured_profile_name_for_upload(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Pass the captured display name through to LinkedIn's human-readable resume filename.

    Args:
        tmp_path (Path): Isolated config and profile snapshot.
        monkeypatch (MonkeyPatch): Replace the live publisher.

    Returns:
        None: The captured profile name reaches the publication boundary.
    """
    config = tmp_path / "resumeme.config.yaml"
    config.write_text("linkedin: {username: example-person}\n")
    save_profile(Profile(username="example-person", name="Alex Example"), tmp_path / "data/profile.json")
    publisher = MagicMock(return_value="alex-example-resume-fixture.pdf")
    monkeypatch.setattr("resumeme.cli.publish_resume", publisher)

    assert main(["--config", str(config), "publish-resume", "--pdf", "signed/resume.pdf", "--dry-run"]) == 0
    assert publisher.call_args.kwargs["profile_name"] == "Alex Example"


def test_upload_workflow_requires_verified_current_tag_and_explicit_settings() -> None:
    """
    Keep publication in its own tag job with the same-run signed artifact and narrow credentials.

    Returns:
        None: Every network publication step is gated by explicit configuration and current-release selection.
    """
    root = REPOSITORY_ROOT
    caller = yaml.safe_load((root / ".github/workflows/ci.yml").read_text())["jobs"]["linkedin-resume-stage"]
    workflow = yaml.safe_load((root / ".github/workflows/stage-linkedin-resume.yml").read_text())
    job = workflow["jobs"]["resume"]
    assert caller["needs"] == ["source", "release-stage"]
    assert set(caller["secrets"]) == {
        "LINKEDIN_USERNAME",
        "LINKEDIN_PASSWORD",
        "RESUMEME_CACHE_PRIVATE_KEY",
        "RESUMEME_CACHE_PUBLIC_KEY",
        "RESUMEME_CACHE_KEY_PASSWORD",
    }
    assert workflow["permissions"] == {"contents": "read"}

    for stage in (caller, job):
        assert stage["if"] == "github.event_name == 'push' && startsWith(github.ref, 'refs/tags/')"

    assert job["concurrency"] == {"group": "resumeme-linkedin-resume-${{ github.repository }}", "cancel-in-progress": False}
    steps = job["steps"]
    settings = next(step for step in steps if step.get("id") == "settings")
    latest = next(step for step in steps if step.get("id") == "latest")
    assert settings["run"] == "poetry run python scripts/ci/resume-settings.py"
    assert latest["if"] == "steps.settings.outputs.enabled == 'true'"
    download = next(step for step in steps if step.get("uses", "").startswith("actions/download-artifact@"))
    assert download["with"] == {"name": "signed-resume", "path": ".cache/publication"}
    verify = next(step for step in steps if step.get("run") == "bash scripts/release/verify.sh")
    upload = steps[-1]
    assert upload["uses"] == "./.github/actions/linkedin-session"
    assert upload["with"]["command"] == "publish-resume"
    assert set(upload["env"]) == {"LINKEDIN_USERNAME", "LINKEDIN_PASSWORD", "RESUMEME_LOG_LEVEL", "PYTHONUNBUFFERED"}
    assert upload["env"]["RESUMEME_LOG_LEVEL"] == "DEBUG"
    assert steps.index(download) < steps.index(verify) < steps.index(upload)

    for step in (download, verify, upload):
        assert step["if"] == "steps.latest.outputs.current == 'true'"
        assert not step.get("continue-on-error", False)


@pytest.mark.parametrize("latest_tag", ["resume-new", "resume-old"])
def test_old_tag_retry_does_not_select_an_obsolete_resume(latest_tag: str, tmp_path: Path) -> None:
    """
    Exercise the real latest-release shell gate without contacting GitHub.

    Args:
        latest_tag (str): Current GitHub release returned by the command stub.
        tmp_path (Path): Disposable command and Actions output paths.

    Returns:
        None: Only a matching latest release enables downstream upload.
    """
    root = REPOSITORY_ROOT
    workflow = yaml.safe_load((root / ".github/workflows/stage-linkedin-resume.yml").read_text())
    gate = next(step for step in workflow["jobs"]["resume"]["steps"] if step.get("id") == "latest")
    gh = tmp_path / "gh"
    gh.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$TEST_LATEST_TAG"\n')
    gh.chmod(0o700)
    output = tmp_path / "output"
    output.touch()
    environment = dict(
        os.environ,
        PATH=f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        GITHUB_OUTPUT=str(output),
        GITHUB_REPOSITORY="example/resumeme",
        RELEASE_TAG="resume-new",
        TEST_LATEST_TAG=latest_tag,
    )
    subprocess.run(["bash", "-euo", "pipefail", "-c", gate["run"]], cwd=root, env=environment, check=True, capture_output=True)
    assert output.read_text() == ("current=true\n" if latest_tag == "resume-new" else "")
