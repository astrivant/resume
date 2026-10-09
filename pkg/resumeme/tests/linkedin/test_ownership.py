"""
Verify signing identity reconciliation without writing to a real LinkedIn account.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, call

import pytest
from attrs import evolve
from jsonschema import ValidationError
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.keys import Keys

from resumeme.cli import main
from resumeme.config import Capture, Config, LinkedIn, Ownership, load_config
from resumeme.linkedin.identity import ownership_block, reconcile_about, release_destination
from resumeme.linkedin.ownership import _about_editor_open, _about_text, _editor, _fill_about, _update_about, publish_ownership
from resumeme.signing import public_key_fingerprint

if TYPE_CHECKING:
    from typing import Literal

    from pytest import MonkeyPatch

_FINGERPRINT = "SHA256:" + "a" * 64
_BLOCK = ownership_block(_FINGERPRINT, "https://github.com/fork/resumeme/releases")


@pytest.mark.parametrize("original", ["", "Platform engineer.", "First paragraph.\n\nSecond \u2014 café \u2615.\n", "Intro\n\n"])
def test_append_preserves_personal_text(original: str) -> None:
    """
    Retain all original text and make repeated updates idempotent.

    Args:
        original (str): Empty, multiline, or Unicode About text.

    Returns:
        None: The new block appears once without changing personal text.
    """
    updated = reconcile_about(original, _BLOCK)
    assert updated.startswith(original)
    assert updated.endswith(_BLOCK)
    assert updated.count("resume signature:") == 1
    assert reconcile_about(updated, _BLOCK) == updated


def test_rotation_preserves_surrounding_paragraphs() -> None:
    """
    Rotate the public key and release URL while preserving text on both sides.

    Returns:
        None: Only the exact recognized pair changes.
    """
    replacement = ownership_block("SHA256:" + "b" * 64, "https://example.org/resume")
    assert reconcile_about("Before\n\n" + _BLOCK + "\n\nAfter", replacement) == "Before\n\n" + replacement + "\n\nAfter"


def test_editor_added_blank_paragraph_does_not_duplicate_the_managed_block() -> None:
    """
    Recognize LinkedIn's rich text spacing when About is read on a later run.

    Returns:
        None: The one managed identity pair remains idempotent across paragraph breaks.
    """
    signature, releases = _BLOCK.splitlines()
    current = f"Personal About.\n\n{signature}\n\n{releases}"

    normalized = reconcile_about(current, _BLOCK)

    assert normalized == f"Personal About.\n\n{_BLOCK}"
    assert reconcile_about(normalized, _BLOCK) == normalized


@pytest.mark.parametrize("current", ["resume signature: invalid", "releases: https://example.org", _BLOCK + "\n" + _BLOCK])
def test_ambiguous_lines_fail_without_rewriting(current: str) -> None:
    """
    Reject malformed and duplicated managed text instead of guessing ownership.

    Args:
        current (str): Ambiguous manually edited block.

    Returns:
        None: Reconciliation fails before browser mutation.
    """
    with pytest.raises(ValueError, match="ambiguous"):
        reconcile_about(current, _BLOCK)


def test_destination_prefers_explicit_fork_then_actions(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Follow each fork's repository without using the personal GitHub profile link.

    Args:
        tmp_path (Path): Checkout-independent configuration directory.
        monkeypatch (MonkeyPatch): Scoped Actions repository environment without Git installed.

    Returns:
        None: Explicit repository and short link override automatic Actions context.
    """
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("GITHUB_REPOSITORY", "organization/fork")
    assert release_destination(Ownership(), tmp_path) == "https://github.com/organization/fork/releases"
    assert release_destination(Ownership(repository="person/project"), tmp_path) == "https://github.com/person/project/releases"
    assert release_destination(Ownership(releases_url="https://example.org/cv"), tmp_path) == "https://example.org/cv"


def test_required_destination_without_git_needs_configuration(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Require a release destination for publication even when Git cannot discover one.

    Args:
        tmp_path (Path): Empty directory with neither executables nor a checkout.
        monkeypatch (MonkeyPatch): Remove optional Git and Actions repository discovery.

    Returns:
        None: Publication receives an actionable configuration error while explicit destinations remain usable.
    """
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))

    with pytest.raises(ValueError, match=r"Set publishing\.linkedin\.ownership\.repository to OWNER/REPO"):
        release_destination(Ownership(), tmp_path)

    assert release_destination(Ownership(repository="person/project"), tmp_path) == "https://github.com/person/project/releases"
    assert release_destination(Ownership(releases_url="https://example.org/cv"), tmp_path) == "https://example.org/cv"


@pytest.mark.parametrize(
    "origin", ["git@github.com:owner/fork.git", "https://github.com/owner/fork.git", "ssh://git@github.com/owner/fork.git"]
)
def test_destination_reads_local_origin(origin: str, tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Resolve common GitHub origin forms from an actual local repository.

    Args:
        origin (str): Git remote transport syntax.
        tmp_path (Path): Disposable Git repository.
        monkeypatch (MonkeyPatch): Environment isolation from Actions.

    Returns:
        None: The origin supplies the fork's release destination.
    """
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "remote", "add", "origin", origin], check=True)
    assert release_destination(Ownership(), tmp_path) == "https://github.com/owner/fork/releases"


@pytest.mark.parametrize("url", ["http://example.org", "https://user:password@example.org", "https://example.org/\nInjected", "https://"])
def test_invalid_destinations_fail(url: str, tmp_path: Path) -> None:
    """
    Reject nonpublic or multiline destinations before a browser is started.

    Args:
        url (str): Invalid release destination.
        tmp_path (Path): Unused origin directory.

    Returns:
        None: URL validation fails locally.
    """
    with pytest.raises(ValueError, match="HTTPS"):
        release_destination(Ownership(releases_url=url), tmp_path)


def test_public_key_fingerprint_uses_der(tmp_path: Path) -> None:
    """
    Compare the shared fingerprint with independently exported canonical key bytes.

    Args:
        tmp_path (Path): Temporary test-only keys, never used for publishing.

    Returns:
        None: PEM line wrapping does not change the signing identity.
    """
    private = tmp_path / "fixture.key"
    public = tmp_path / "cosign.pub"
    subprocess.run(["openssl", "genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-256", "-out", str(private)], check=True)
    subprocess.run(["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)], check=True)
    der = subprocess.run(["openssl", "pkey", "-pubin", "-in", str(public), "-outform", "DER"], check=True, capture_output=True).stdout
    expected = "SHA256:" + hashlib.sha256(der).hexdigest()
    assert public_key_fingerprint(public) == expected
    lines = public.read_text().splitlines()
    public.write_text(lines[0] + "\n" + "".join(lines[1:-1]) + "\n" + lines[-1] + "\n")
    assert public_key_fingerprint(public) == expected

    # Private input must not be mistaken for a public identity or echoed in an error message.
    with pytest.raises(ValueError, match="public key"):
        public_key_fingerprint(private)


@pytest.mark.parametrize(
    "ownership", ["update_about: yes", "repository: not-a-repository", "releases_url: http://example.org", "unknown: true"]
)
def test_ownership_schema_rejects_invalid_values(ownership: str, tmp_path: Path) -> None:
    """
    Keep ownership configuration strict before any browser or CI work.

    Args:
        ownership (str): Invalid inline JSON-like ownership settings.
        tmp_path (Path): Temporary configuration directory.

    Returns:
        None: The schema rejects invalid types, unknown settings, and malformed destinations.
    """
    path = tmp_path / "resumeme.config.yaml"

    # Quote a boolean-looking string to prevent YAML from converting this type-error case to True.
    path.write_text("linkedin:\n  username: test-owner\n  ownership: {" + ownership.replace("yes", "'yes'") + "}\n")

    with pytest.raises(ValidationError):
        load_config(path)


def _config() -> Config:
    """
    Use two immediate attempts for deterministic browser reconciliation tests.

    Returns:
        Config: Minimal owner identity and retry policy.
    """
    return Config(linkedin=LinkedIn("test-owner"), capture=Capture(retry_attempts=2, retry_backoff_seconds=0))


def _field(value: str, maximum: str | None = None) -> MagicMock:
    """
    Model a textarea that retains typed text and reports a browser character limit.

    Args:
        value (str): Initial server text.
        maximum (str | None): Optional HTML maxlength.

    Returns:
        MagicMock: Mutable textarea supporting the Selenium methods used by the updater.
    """
    element = MagicMock()
    state = {"value": value, "maxlength": maximum}
    element.get_attribute.side_effect = state.get
    element.clear.side_effect = lambda: state.update(value="")
    element.send_keys.side_effect = lambda text: state.update(value=text)
    return element


def test_rich_about_text_ignores_visual_wrapping() -> None:
    """
    Read paragraph structure without turning editor layout into authored line breaks.

    Returns:
        None: Rich editor text comes from its DOM structure, not layout-dependent innerText.
    """
    driver, field = MagicMock(), MagicMock()
    field.get_attribute.return_value = "true"
    driver.execute_script.return_value = "First paragraph.\n\n\nSecond paragraph with a hard\nbreak."

    assert _about_text(driver, field) == "First paragraph.\n\nSecond paragraph with a hard\nbreak."
    script, argument = driver.execute_script.call_args.args
    assert "innerText" not in script
    assert "childNodes" in script
    assert argument is field


def test_rich_about_writer_separates_paragraphs_with_one_blank_row() -> None:
    """
    Preserve paragraph spacing in LinkedIn's rich editor without adding extra rows.

    Returns:
        None: The editor receives two Enter events for a blank row, then extraction collapses editor padding.
    """
    driver, field = MagicMock(), MagicMock()
    driver.capabilities = {"platformName": "macOS"}
    field.get_attribute.return_value = "true"

    _fill_about(driver, field, "First paragraph.\n\nSecond paragraph.")

    assert field.send_keys.call_args_list == [
        call(Keys.COMMAND, "a"),
        call(Keys.BACKSPACE),
        call("First paragraph."),
        call(Keys.ENTER),
        call(Keys.ENTER),
        call("Second paragraph."),
    ]


def test_follow_up_modal_does_not_count_as_open_about_editor() -> None:
    """
    Treat LinkedIn's post-save notifications or upsell dialogs as a completed About submission.

    Returns:
        None: Only a visible dialog containing the About field blocks persisted read-back.
    """
    driver, dialog, field = MagicMock(), MagicMock(), MagicMock()
    driver.find_elements.return_value = [dialog]
    dialog.is_displayed.return_value = True
    dialog.find_elements.return_value = []

    assert not _about_editor_open(driver)

    dialog.find_elements.return_value = [field]
    field.is_displayed.return_value = True

    assert _about_editor_open(driver)


@pytest.mark.parametrize("dry_run,current", [(True, "Personal text"), (False, "Personal text\n\n" + _BLOCK)])
def test_preview_and_unchanged_about_never_save(dry_run: bool, current: str, tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Avoid browser mutations for previews and an already matching identity.

    Args:
        dry_run (bool): Whether this invocation is a preview.
        current (str): Existing server text.
        tmp_path (Path): Backup root, which must remain untouched.
        monkeypatch (MonkeyPatch): Editor boundary replacement.

    Returns:
        None: No textarea clear, typing, Save, or backup occurs.
    """
    field, save = _field(current), MagicMock()
    monkeypatch.setattr("resumeme.linkedin.ownership._editor", MagicMock(return_value=(field, save)))
    assert _update_about(MagicMock(), _config(), tmp_path, _BLOCK, dry_run=dry_run) == reconcile_about(current, _BLOCK)
    field.clear.assert_not_called()
    field.send_keys.assert_not_called()
    save.click.assert_not_called()
    assert not (tmp_path / ".cache/ownership").exists()


def test_success_saves_backup_and_verifies_persistence(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Submit complete reconciled text and independently confirm the saved server value.

    Args:
        tmp_path (Path): Private backup directory owner.
        monkeypatch (MonkeyPatch): Fresh editor boundary substitution.

    Returns:
        None: One Save occurs and the original About remains recoverable.
    """
    original = "Engineer.\n\nOwn words."
    expected = reconcile_about(original, _BLOCK)
    field, save = _field(original), MagicMock()
    editor = MagicMock(side_effect=[(field, save), (_field(expected), MagicMock())])
    monkeypatch.setattr("resumeme.linkedin.ownership._editor", editor)
    driver = MagicMock()
    driver.find_elements.return_value = []
    assert _update_about(driver, _config(), tmp_path, _BLOCK, dry_run=False) == expected
    save.click.assert_called_once()
    field.send_keys.assert_called_once_with(expected)
    backup = next((tmp_path / ".cache/ownership").glob("about-before-*.txt"))
    assert backup.read_text() == original
    assert backup.stat().st_mode & 0o777 == 0o600
    assert editor.call_count == 2


@pytest.mark.parametrize("concurrent", [False, True])
def test_uncertain_save_rereads_before_retry(concurrent: bool, tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Recognize a successful timed-out Save and stop if somebody else changed About.

    Args:
        concurrent (bool): Whether another writer changed the saved text.
        tmp_path (Path): Ignored backup root.
        monkeypatch (MonkeyPatch): Fresh reads supplied per browser attempt.

    Returns:
        None: The retry never blindly submits the old text again.
    """
    field, save = _field("Original"), MagicMock()
    desired = reconcile_about("Original", _BLOCK)
    later_save = MagicMock()
    save.click.side_effect = TimeoutException("response lost")
    fresh = "Concurrent edit" if concurrent else desired
    monkeypatch.setattr("resumeme.linkedin.ownership._editor", MagicMock(side_effect=[(field, save), (_field(fresh), later_save)]))

    if concurrent:
        with pytest.raises(ValueError, match="changed during"):
            _update_about(MagicMock(), _config(), tmp_path, _BLOCK, dry_run=False)
    else:
        assert _update_about(MagicMock(), _config(), tmp_path, _BLOCK, dry_run=False) == desired

    save.click.assert_called_once()
    later_save.click.assert_not_called()


def test_about_limit_fails_before_mutation(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Respect the browser's character limit without truncating personal text.

    Args:
        tmp_path (Path): Backup root, left untouched.
        monkeypatch (MonkeyPatch): Editor substitution with an explicit length bound.

    Returns:
        None: No text is changed and Save is not attempted.
    """
    field, save = _field("Existing", "10"), MagicMock()
    monkeypatch.setattr("resumeme.linkedin.ownership._editor", MagicMock(return_value=(field, save)))

    with pytest.raises(ValueError, match="character limit"):
        _update_about(MagicMock(), _config(), tmp_path, _BLOCK, dry_run=False)

    field.clear.assert_not_called()
    save.click.assert_not_called()


@pytest.mark.parametrize("url", ["https://www.linkedin.com/in/another-person/", "https://other.example/in/test-owner/"])
def test_editor_rejects_wrong_owner_or_origin(url: str, monkeypatch: MonkeyPatch) -> None:
    """
    Prevent any editor navigation after a profile redirect crosses the owner boundary.

    Args:
        url (str): Browser location after navigation.
        monkeypatch (MonkeyPatch): Read-only navigation replacement.

    Returns:
        None: Owner verification rejects the page before looking for editing controls.
    """
    driver = MagicMock()
    driver.current_url = url
    driver.find_elements.return_value = [MagicMock()]
    navigate = MagicMock()
    monkeypatch.setattr("resumeme.linkedin.ownership._navigate", navigate)

    with pytest.raises(ValueError, match="configured owner"):
        _editor(driver, _config())

    assert navigate.call_count == 1


def test_other_members_profile_cannot_be_edited(monkeypatch: MonkeyPatch) -> None:
    """
    Require owner-only edit links even when the URL matches the configured slug.

    Args:
        monkeypatch (MonkeyPatch): Read-only navigation replacement.

    Returns:
        None: No edit route is opened for a profile with no owner controls.
    """
    driver = MagicMock()
    driver.current_url = "https://www.linkedin.com/in/test-owner/"
    driver.find_elements.side_effect = [[MagicMock()], []]
    navigate = MagicMock()
    monkeypatch.setattr("resumeme.linkedin.ownership._navigate", navigate)

    with pytest.raises(ValueError, match="owner edit control"):
        _editor(driver, _config())

    assert navigate.call_count == 1


def test_cli_ownership_does_not_require_snapshot(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Make the explicit live command usable before the first profile capture.

    Args:
        tmp_path (Path): Minimal configuration with no data directory.
        monkeypatch (MonkeyPatch): Browser call boundary replacement.

    Returns:
        None: The command forwards preview and key arguments without loading a snapshot.
    """
    config = tmp_path / "resumeme.config.yaml"
    config.write_text("linkedin:\n  username: test-owner\n")
    update = MagicMock(return_value=_BLOCK)
    monkeypatch.setattr("resumeme.cli.publish_ownership", update)
    assert main(["--config", str(config), "publish-ownership", "--public-key", "cosign.pub", "--dry-run"]) == 0
    assert update.call_args.kwargs["dry_run"] is True
    assert update.call_args.args[2] == Path("cosign.pub")
    assert not (tmp_path / "data").exists()
    assert load_config(config).linkedin.ownership.update_about is False


def test_missing_credentials_fail_before_browser(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Report missing CI credentials without opening Firefox or inspecting any key.

    Args:
        tmp_path (Path): Unused project root.
        monkeypatch (MonkeyPatch): Empty environment and browser sentinel.

    Returns:
        None: Headless setup fails without side effects.
    """
    monkeypatch.delenv("LINKEDIN_USERNAME", raising=False)
    monkeypatch.delenv("LINKEDIN_PASSWORD", raising=False)
    firefox = MagicMock()
    monkeypatch.setattr("resumeme.linkedin.ownership._browser", firefox)

    with pytest.raises(ValueError, match="require LINKEDIN"):
        publish_ownership(_config(), tmp_path, tmp_path / "missing.pub", headless=True)

    firefox.assert_not_called()


@pytest.mark.parametrize("browser", ["firefox", "chrome"])
def test_ownership_uses_configured_browser(tmp_path: Path, monkeypatch: MonkeyPatch, browser: Literal["firefox", "chrome"]) -> None:
    """
    Use the same browser selection for live About previews as for profile capture.

    Args:
        tmp_path (Path): Temporary browser state directory.
        monkeypatch (MonkeyPatch): Browser, public key, and editor boundaries.
        browser (Literal["firefox", "chrome"]): Selected Selenium browser.

    Returns:
        None: Selection and login settings reach the shared browser client without submitting a real edit.
    """
    config = evolve(_config(), capture=Capture(browser=browser))
    session = MagicMock()
    driver = session.return_value.__enter__.return_value
    login = MagicMock()
    update = MagicMock(return_value=_BLOCK)
    monkeypatch.setattr("resumeme.linkedin.ownership._browser", session)
    monkeypatch.setattr("resumeme.linkedin.ownership._login", login)
    monkeypatch.setattr("resumeme.linkedin.ownership._update_about", update)
    monkeypatch.setattr("resumeme.linkedin.ownership.public_key_fingerprint", MagicMock(return_value=_FINGERPRINT))
    monkeypatch.setattr(
        "resumeme.linkedin.ownership.release_destination", MagicMock(return_value="https://github.com/fork/resumeme/releases")
    )
    assert publish_ownership(config, tmp_path, tmp_path / "key.pub", dry_run=True) == _BLOCK
    session.assert_called_once_with(tmp_path, config.capture, None, headless=False)
    login.assert_called_once_with(driver, config.capture, headless=False, profile_username=config.linkedin.username)
    update.assert_called_once_with(driver, config, tmp_path, _BLOCK, dry_run=True)


@pytest.mark.parametrize("edit_route", ["edit/intro/", "edit/forms/summary/new/"])
def test_editor_supports_empty_and_existing_about(edit_route: str, monkeypatch: MonkeyPatch) -> None:
    """
    Open only the configured owner's summary form using observable owner controls.

    Args:
        edit_route (str): Owner control available on a minimal or populated profile.
        monkeypatch (MonkeyPatch): Navigation replacement retaining browser URL transitions.

    Returns:
        None: The unique visible About field and Save control are returned from the owner's dialog.
    """
    driver = MagicMock()
    link, dialog, field, save, cancel = (MagicMock() for _ in range(5))
    link.get_attribute.return_value = "https://www.linkedin.com/in/test-owner/" + edit_route
    save.text, cancel.text = "Save", "Cancel"
    dialog.find_elements.side_effect = lambda selector_type, selector: (
        [field] if "textarea" in selector or "contenteditable" in selector else [cancel, save]
    )
    elements = {
        'main h1, section[aria-label="Primary content"] h2': [MagicMock()],
        "a[href]": [link],
        'dialog[open], [role="dialog"]': [dialog],
        'textarea, [contenteditable="true"][role="textbox"][aria-label="About"]': [field],
    }
    driver.find_elements.side_effect = lambda selector_type, selector: elements[selector]
    monkeypatch.setattr("resumeme.linkedin.ownership._navigate", lambda page, url, settings: setattr(page, "current_url", url))
    assert _editor(driver, _config()) == (field, save)
    expected_path = "" if edit_route.endswith("summary/new/") else "edit/forms/summary/new/"
    assert driver.current_url == f"https://www.linkedin.com/in/test-owner/{expected_path}"
    save.click.assert_not_called()


def test_truncated_input_is_never_submitted(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Detect field truncation even when the editor does not expose maxlength.

    Args:
        tmp_path (Path): Ignored backup root.
        monkeypatch (MonkeyPatch): Textarea substitution that drops typed content.

    Returns:
        None: Save is not clicked after partial text acceptance.
    """
    field, save = _field("Original"), MagicMock()
    field.send_keys.side_effect = None
    monkeypatch.setattr("resumeme.linkedin.ownership._editor", MagicMock(return_value=(field, save)))

    with pytest.raises(ValueError, match="complete About text"):
        _update_about(MagicMock(), _config(), tmp_path, _BLOCK, dry_run=False)

    save.click.assert_not_called()


def test_unconfirmed_save_is_not_reported_as_success(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Require a fresh editor read to match the submitted text before reporting success.

    Args:
        tmp_path (Path): Backup root.
        monkeypatch (MonkeyPatch): Editor reads returning unchanged server text after Save.

    Returns:
        None: Failed persistence remains an actionable failure.
    """
    field, save = _field("Original"), MagicMock()
    monkeypatch.setattr("resumeme.linkedin.ownership._editor", MagicMock(side_effect=[(field, save), (_field("Original"), MagicMock())]))
    driver = MagicMock()
    driver.find_elements.return_value = []

    with pytest.raises(ValueError, match="did not retain"):
        _update_about(driver, _config(), tmp_path, _BLOCK, dry_run=False)

    save.click.assert_called_once()
