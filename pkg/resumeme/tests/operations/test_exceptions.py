"""
Verify the package error boundary and compatibility with existing callers and retries.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from selenium.common.exceptions import NoSuchElementException, NoSuchWindowException, TimeoutException

from resumeme.cli import main
from resumeme.compiler.asts.parsing import parse_profile
from resumeme.config import project_path
from resumeme.exceptions import (
    BrowserElementError,
    BrowserWaitError,
    BrowserWindowError,
    ConfigurationError,
    ProfileError,
    ResumemeError,
)
from resumeme.linkedin.retrying import retry

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import CaptureFixture, MonkeyPatch
    from selenium.common.exceptions import WebDriverException


def test_validation_failures_share_package_boundary(tmp_path: Path) -> None:
    """
    Expose domain failures without breaking callers that catch invalid input.

    Args:
        tmp_path (Path): Configuration root for checking path ownership.

    Returns:
        None: Public operations expose specific errors compatible with both error boundaries.
    """
    with pytest.raises(ConfigurationError, match="within the configuration directory") as configuration:
        project_path(tmp_path, "../outside")

    with pytest.raises(ProfileError, match="No profile heading found") as profile:
        parse_profile("<main></main>", "example-person")

    for error in (configuration.value, profile.value):
        assert isinstance(error, ResumemeError)
        assert isinstance(error, ValueError)


@pytest.mark.parametrize(
    "error_type,legacy_type",
    [
        (BrowserElementError, NoSuchElementException),
        (BrowserWindowError, NoSuchWindowException),
        (BrowserWaitError, TimeoutException),
    ],
)
def test_browser_errors_preserve_selenium_diagnostics(error_type: type[WebDriverException], legacy_type: type[WebDriverException]) -> None:
    """
    Retain Selenium constructors, diagnostics, and catch compatibility across multiple inheritance.

    Args:
        error_type (type[WebDriverException]): Package-defined browser failure.
        legacy_type (type[WebDriverException]): Selenium base used by existing callers.

    Returns:
        None: Message formatting, screenshots, and browser stack traces remain intact.
    """
    error = error_type("Browser state changed", "screenshot", ["browser frame"])
    legacy = legacy_type("Browser state changed", "screenshot", ["browser frame"])
    assert isinstance(error, ResumemeError)
    assert isinstance(error, legacy_type)
    assert str(error) == str(legacy)
    assert error.msg == legacy.msg
    assert error.screen == legacy.screen
    assert error.stacktrace == legacy.stacktrace


@pytest.mark.parametrize("error", [BrowserElementError("Dialog missing"), BrowserWaitError("Save not confirmed")])
def test_browser_errors_retain_retry_and_failure_identity(monkeypatch: MonkeyPatch, error: BrowserElementError | BrowserWaitError) -> None:
    """
    Let existing transient policies retry package errors and preserve their final failure.

    Args:
        monkeypatch (MonkeyPatch): Replaces delays with a deterministic observation point.
        error (BrowserElementError | BrowserWaitError): Package error supplied by a browser state check.

    Returns:
        None: Legacy retry types catch the failure without wrapping or losing its chained cause.
    """
    sleep = MagicMock()
    operation = MagicMock(side_effect=error)
    error.__cause__ = OSError("Lost browser response")
    monkeypatch.setattr("resumeme.linkedin.retrying.time.sleep", sleep)

    with pytest.raises(ResumemeError) as failure:
        retry(operation, attempts=2, backoff=1, exceptions=(NoSuchElementException, TimeoutException))

    assert operation.call_count == 2
    sleep.assert_called_once_with(1)
    assert failure.value is error
    assert isinstance(failure.value.__cause__, OSError)


def test_cli_handles_common_package_error(monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]) -> None:
    """
    Report any package failure through the CLI's existing error status and structured output.

    Args:
        monkeypatch (MonkeyPatch): Injects a package failure at configuration loading.
        capsys (CaptureFixture[str]): Captures stdout and stderr emitted by the CLI.

    Returns:
        None: A root package error produces an actionable record and exit status two.
    """
    monkeypatch.delenv("RESUMEME_LOG_LEVEL", raising=False)
    monkeypatch.setattr("resumeme.cli.load_config", MagicMock(side_effect=ResumemeError("Profile needs review")))
    assert main(["validate"]) == 2
    captured = capsys.readouterr()
    record = json.loads(captured.out)
    assert record["body"] == "Profile needs review"
    assert record["attributes"]["error.type"] == "ResumemeError"
    assert captured.err == ""
