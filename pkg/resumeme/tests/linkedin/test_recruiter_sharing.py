"""
Verify explicit recruiter-sharing overrides without contacting LinkedIn or changing account privacy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
import yaml
from jsonschema import ValidationError
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By

from resumeme.config import Capture, Config, LinkedIn, LinkedInResume, load_config
from resumeme.exceptions import BrowserError
from resumeme.linkedin.resume import publish_resume
from resumeme.linkedin.resume_sharing import _recruiter_control, _recruiter_sharing, _sharing_enabled

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch


def _config(desired: bool | None) -> Config:
    """
    Select a sharing policy with deterministic, immediate read retries.

    Args:
        desired (bool | None): Explicit enabled or disabled state, or no override.

    Returns:
        Config: Publication-enabled account with bounded test-only wait settings.
    """
    return Config(
        linkedin=LinkedIn(username="example-person", resume=LinkedInResume(publish=True, share_with_recruiters=desired)),
        capture=Capture(page_timeout_seconds=0, retry_attempts=3, retry_backoff_seconds=0),
    )


@pytest.mark.parametrize("desired", [None, False, True])
def test_config_preserves_tristate_intent(desired: bool | None, tmp_path: Path) -> None:
    """
    Preserve null, false, and true distinctly through schema validation and typed loading.

    Args:
        desired (bool | None): Requested setting.
        tmp_path (Path): Isolated YAML fixture directory.

    Returns:
        None: The loaded override retains the exact user intent, with None as the default.
    """
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"linkedin": {"username": "example-person", "resume": {"share_with_recruiters": desired}}}))
    assert load_config(path).linkedin.resume.share_with_recruiters is desired
    assert LinkedInResume().share_with_recruiters is None


@pytest.mark.parametrize("invalid", ["false", "true", 0, 1])
def test_config_rejects_coerced_privacy_values(invalid: str | int, tmp_path: Path) -> None:
    """
    Reject strings and numbers instead of coercing a privacy override to boolean.

    Args:
        invalid (str | int): Ambiguous user input.
        tmp_path (Path): Isolated YAML fixture directory.

    Returns:
        None: Invalid policy fails before any browser interaction.
    """
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"linkedin": {"username": "example-person", "resume": {"share_with_recruiters": invalid}}}))

    with pytest.raises(ValidationError):
        load_config(path)


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("enabled", [False, True])
def test_switch_and_native_checkbox_states_are_read(native: bool, enabled: bool) -> None:
    """
    Read both accessible switches and native checkboxes without assuming missing state is disabled.

    Args:
        native (bool): Whether the fixture uses a native checkbox instead of an ARIA switch.
        enabled (bool): Stored control state.

    Returns:
        None: Each supported representation produces its exact boolean state.
    """
    control = MagicMock()
    control.tag_name = "input" if native else "button"
    attributes = {"aria-checked": None if native else str(enabled).lower(), "type": "checkbox" if native else "button"}
    control.get_attribute.side_effect = attributes.get
    control.is_selected.return_value = enabled
    assert _sharing_enabled(control) is enabled


@pytest.mark.parametrize("state", [None, "mixed", "unknown"])
def test_indeterminate_state_fails_closed(state: str | None) -> None:
    """
    Refuse to toggle a control whose current state cannot be established.

    Args:
        state (str | None): Unsupported switch state.

    Returns:
        None: An actionable error precedes any mutation.
    """
    control = MagicMock(tag_name="button")
    control.get_attribute.return_value = state

    with pytest.raises(BrowserError, match="could not be determined"):
        _sharing_enabled(control)


@pytest.mark.parametrize("hidden", [False, True])
def test_exact_recruiter_control_avoids_neighboring_preferences(hidden: bool) -> None:
    """
    Select recruiter sharing independently of the adjacent resume-saving preference.

    Args:
        hidden (bool): Whether the native control uses a visible associated label for clicks.

    Returns:
        None: Only the recruiter control and its proper click target are selected.
    """
    driver = MagicMock()
    other = MagicMock(accessible_name="Save resumes and application data")
    other.get_attribute.return_value = "save-resumes"
    recruiter = MagicMock(accessible_name="" if hidden else "Share resume data with recruiters")
    recruiter.get_attribute.return_value = "recruiter-sharing"
    recruiter.is_displayed.return_value = not hidden
    label = MagicMock(text="Share resume data with recruiters")
    label.get_attribute.return_value = "recruiter-sharing"
    driver.find_elements.side_effect = [[other, recruiter], [label], [label]]
    assert _recruiter_control(driver) == (recruiter, label if hidden else recruiter)
    other.click.assert_not_called()


def test_artdeco_switch_uses_visible_wrapper_when_input_is_hidden() -> None:
    """
    Click LinkedIn's visible switch wrapper instead of its zero-size accessibility label.

    Returns:
        None: The hidden state input remains the source of truth and its visible wrapper is the click target.
    """
    driver = MagicMock()
    other = MagicMock(accessible_name="Allow LinkedIn to save your resumes and answers")
    other.get_attribute.return_value = "save-resumes"
    recruiter = MagicMock(accessible_name="Allow recruiters to view your resumes")
    recruiter.get_attribute.side_effect = lambda name: {
        "id": "share-resume-toggle",
        "data-artdeco-toggle-button": "true",
    }.get(name)
    recruiter.is_displayed.return_value = False
    label = MagicMock(text="Allow recruiters to view your resumes")
    label.get_attribute.return_value = "share-resume-toggle"
    toggle = MagicMock()
    toggle.get_attribute.return_value = "artdeco-toggle artdeco-toggle--32dp"
    toggle.is_displayed.return_value = True
    recruiter.find_element.return_value = toggle
    driver.find_elements.side_effect = [[other, recruiter], [], [label]]

    assert _recruiter_control(driver) == (recruiter, toggle)
    recruiter.find_element.assert_called_once_with(By.XPATH, "..")
    label.click.assert_not_called()


def test_ambiguous_controls_fail_closed() -> None:
    """
    Avoid choosing between duplicate visible sharing settings.

    Returns:
        None: No candidate is clicked when the UI is ambiguous.
    """
    driver = MagicMock()
    control = MagicMock(accessible_name="Share resume data with recruiters")
    driver.find_elements.side_effect = [[control, control], [], []]

    with pytest.raises(BrowserError, match="multiple recruiter-sharing"):
        _recruiter_control(driver)

    control.click.assert_not_called()


def test_null_policy_never_reads_or_changes_the_control(monkeypatch: MonkeyPatch) -> None:
    """
    Preserve default behavior without depending on recruiter settings markup.

    Args:
        monkeypatch (MonkeyPatch): Settings navigation recorder.

    Returns:
        None: The default leaves the entire sharing flow untouched.
    """
    settings = MagicMock()
    monkeypatch.setattr("resumeme.linkedin.resume_settings._settings", settings)
    _recruiter_sharing(MagicMock(), _config(None), dry_run=False)
    settings.assert_not_called()


@pytest.mark.parametrize("desired", [False, True])
@pytest.mark.parametrize("dry_run", [False, True])
def test_satisfied_policy_and_preview_do_not_click(desired: bool, dry_run: bool, monkeypatch: MonkeyPatch) -> None:
    """
    Keep an already-correct state unchanged and let previews observe a different or disabled state.

    Args:
        desired (bool): Explicit policy.
        dry_run (bool): Preview a differing disabled control, or confirm an already-correct live state.
        monkeypatch (MonkeyPatch): Deterministic settings and state observations.

    Returns:
        None: Both outcomes require zero toggle clicks.
    """
    control = MagicMock()
    control.is_enabled.return_value = not dry_run
    monkeypatch.setattr("resumeme.linkedin.resume_settings._settings", MagicMock())
    monkeypatch.setattr("resumeme.linkedin.resume_sharing._recruiter_control", MagicMock(return_value=(control, control)))
    monkeypatch.setattr("resumeme.linkedin.resume_sharing._sharing_enabled", MagicMock(return_value=not desired if dry_run else desired))
    _recruiter_sharing(MagicMock(), _config(desired), dry_run=dry_run)
    control.click.assert_not_called()


@pytest.mark.parametrize("desired", [False, True])
@pytest.mark.parametrize("uncertain", [False, True])
def test_toggle_is_submitted_once_and_verified_after_reload(desired: bool, uncertain: bool, monkeypatch: MonkeyPatch) -> None:
    """
    Reconcile successful and uncertain clicks through fresh reads with no second toggle.

    Args:
        desired (bool): Requested enabled or disabled state.
        uncertain (bool): Whether WebDriver loses the click response.
        monkeypatch (MonkeyPatch): Deterministic delayed server persistence.

    Returns:
        None: One click is followed by read retries that confirm the desired state.
    """
    control = MagicMock()

    if uncertain:
        control.click.side_effect = TimeoutException()

    settings = MagicMock()
    monkeypatch.setattr("resumeme.linkedin.resume_settings._settings", settings)
    monkeypatch.setattr("resumeme.linkedin.resume_sharing._recruiter_control", MagicMock(return_value=(control, control)))
    states = [not desired] + ([] if uncertain else [desired]) + [not desired, desired]
    monkeypatch.setattr("resumeme.linkedin.resume_sharing._sharing_enabled", MagicMock(side_effect=states))
    _recruiter_sharing(MagicMock(), _config(desired), dry_run=False)
    control.click.assert_called_once()
    assert settings.call_count == 3


def test_unpersisted_toggle_fails_without_another_click(monkeypatch: MonkeyPatch) -> None:
    """
    Reject a locally updated switch that never persists on LinkedIn.

    Args:
        monkeypatch (MonkeyPatch): Simulate a locally enabled but persistently disabled setting.

    Returns:
        None: Exhausted reads explain the partial result without risking an inverted setting.
    """
    control = MagicMock()
    monkeypatch.setattr("resumeme.linkedin.resume_settings._settings", MagicMock())
    monkeypatch.setattr("resumeme.linkedin.resume_sharing._recruiter_control", MagicMock(return_value=(control, control)))
    monkeypatch.setattr("resumeme.linkedin.resume_sharing._sharing_enabled", MagicMock(side_effect=[False, True, False, False, False]))

    with pytest.raises(BrowserError, match="No second toggle click"):
        _recruiter_sharing(MagicMock(), _config(True), dry_run=False)

    control.click.assert_called_once()


def test_disabled_control_does_not_override_account_constraints(monkeypatch: MonkeyPatch) -> None:
    """
    Leave a disabled control untouched instead of forcing a DOM state or JavaScript click.

    Args:
        monkeypatch (MonkeyPatch): Supply a disabled sharing control with the opposite state.

    Returns:
        None: Publication reports the unavailable setting and performs no mutation.
    """
    control = MagicMock()
    control.is_enabled.return_value = False
    monkeypatch.setattr("resumeme.linkedin.resume_settings._settings", MagicMock())
    monkeypatch.setattr("resumeme.linkedin.resume_sharing._recruiter_control", MagicMock(return_value=(control, control)))
    monkeypatch.setattr("resumeme.linkedin.resume_sharing._sharing_enabled", MagicMock(return_value=False))

    with pytest.raises(BrowserError, match="control is disabled"):
        _recruiter_sharing(MagicMock(), _config(True), dry_run=False)

    control.click.assert_not_called()


@pytest.mark.parametrize("failed", [False, True])
def test_sharing_follows_successful_or_already_saved_resume(failed: bool, tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Apply sharing only after the upload stage confirms a saved resume, including its duplicate-skip path.

    Args:
        failed (bool): Whether resume verification fails before sharing can be applied.
        tmp_path (Path): Temporary upload staging directory.
        monkeypatch (MonkeyPatch): Replace browser boundaries while recording publication order.

    Returns:
        None: Failed uploads cannot alter sharing; successful confirmation precedes the requested override.
    """
    operations = MagicMock()
    operations.upload.return_value = "resume-confirmed.pdf"

    if failed:
        operations.upload.side_effect = BrowserError("Upload unconfirmed")

    for name in ("_browser", "_login", "_navigate", "login_credentials"):
        monkeypatch.setattr(f"resumeme.linkedin.resume.{name}", MagicMock())

    monkeypatch.setattr("resumeme.linkedin.resume._pdf_bytes", MagicMock(return_value=b"verified release bytes"))
    monkeypatch.setattr("resumeme.linkedin.resume._upload_resume", operations.upload)
    monkeypatch.setattr("resumeme.linkedin.resume._recruiter_sharing", operations.sharing)

    if failed:
        with pytest.raises(BrowserError, match="Upload unconfirmed"):
            publish_resume(_config(True), tmp_path, tmp_path / "release.pdf")

        operations.sharing.assert_not_called()
    else:
        assert publish_resume(_config(True), tmp_path, tmp_path / "release.pdf") == "resume-confirmed.pdf"
        assert [record[0] for record in operations.mock_calls] == ["upload", "sharing"]
