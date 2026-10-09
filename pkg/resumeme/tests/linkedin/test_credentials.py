"""
Verify username-variable detection and public profile normalization without account access.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
import yaml
from jsonschema import ValidationError

from resumeme.config import LinkedIn, load_config
from resumeme.exceptions import BrowserError, ConfigurationError
from resumeme.linkedin.capture.profile import capture_profile
from resumeme.linkedin.credentials import login_credentials, profile_username

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch


@pytest.fixture(autouse=True)
def clear_login_environment(monkeypatch: MonkeyPatch) -> None:
    """
    Prevent personal shell credentials from influencing identifier tests.

    Args:
        monkeypatch (MonkeyPatch): Temporarily clears the two supported login variables.

    Returns:
        None: Tests start without configured authentication.
    """
    for name in ("LINKEDIN_USERNAME", "LINKEDIN_PASSWORD"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize(
    "value",
    [
        "example-person",
        "https://www.linkedin.com/in/example-person/",
        "https://linkedin.com/in/example-person?trk=profile#about",
        "http://uk.linkedin.com/in/example-person/",
        "www.linkedin.com/in/example-person/",
        "linkedin.com/in/example-person",
        "//www.linkedin.com/in/example-person/",
    ],
)
def test_profile_identifiers_normalize_in_config(tmp_path: Path, value: str) -> None:
    """
    Use one canonical username across config loading, capture URLs, and snapshot ownership checks.

    Args:
        tmp_path (Path): Temporary configuration directory.
        value (str): Public username or supported profile URL.

    Returns:
        None: Both direct model construction and schema-validated YAML normalize the public identifier.
    """
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"linkedin": {"username": value}}))
    assert load_config(path).linkedin.username == "example-person"
    assert LinkedIn(username=value).username == "example-person"


@pytest.mark.parametrize(
    "value",
    [
        "owner@example.org",
        "https://linkedin.com.evil.example/in/example-person/",
        "https://www.linkedin.com@evil.example/in/example-person/",
        "https://evil.example@www.linkedin.com/in/example-person/",
        "https://www.linkedin.com:443/in/example-person/",
        "https://www.linkedin.com/company/example-person/",
        "https://www.linkedin.com/in/example-person/edit/",
        "https://www.linkedin.com/in/example-person/../other",
        "https://www.linkedin.com/in/example%2Fperson/",
        "https://[invalid/in/example-person/",
    ],
)
def test_invalid_profile_identifiers_are_rejected(tmp_path: Path, value: str) -> None:
    """
    Reject login emails, unrelated destinations, and profile subroutes as configured owners.

    Args:
        tmp_path (Path): Temporary configuration directory.
        value (str): Input outside the supported profile-identifier contract.

    Returns:
        None: Raw schema validation and direct normalization reject the input.
    """
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"linkedin": {"username": value}}))

    with pytest.raises(ValidationError):
        load_config(path)

    with pytest.raises(ConfigurationError):
        profile_username(value)


@pytest.mark.parametrize("identifier", ["owner@example.org", "+1 (202) 555-0100"])
def test_login_credentials_use_existing_username_variable(monkeypatch: MonkeyPatch, identifier: str) -> None:
    """
    Preserve both email and phone login without modifying significant password whitespace.

    Args:
        monkeypatch (MonkeyPatch): Supplies synthetic credentials.
        identifier (str): Email or phone accepted as a private account identifier.

    Returns:
        None: The login identifier is trimmed and the password remains exact.
    """
    monkeypatch.setenv("LINKEDIN_USERNAME", f" {identifier}\n")
    monkeypatch.setenv("LINKEDIN_PASSWORD", " synthetic-password \n")
    assert login_credentials(headless=True) == (identifier, " synthetic-password \n")


@pytest.mark.parametrize(
    "public", ["example-person", "https://www.linkedin.com/in/example-person/?trk=share", "linkedin.com/in/example-person"]
)
@pytest.mark.parametrize("password", ["", "synthetic-password"])
def test_public_identifiers_use_manual_login(monkeypatch: MonkeyPatch, public: str, password: str) -> None:
    """
    Parse a username or URL from the same variable and route public identities to interactive sign-in.

    Args:
        monkeypatch (MonkeyPatch): Supplies the existing login variables.
        public (str): Public username or share URL.
        password (str): Optional password that cannot authenticate a public profile identifier.

    Returns:
        None: Both public forms select the same owner and manual login; headless use explains the required email/phone.
    """
    monkeypatch.setenv("LINKEDIN_USERNAME", public)
    monkeypatch.setenv("LINKEDIN_PASSWORD", password)
    assert login_credentials(headless=False, profile="example-person") == ("", "")

    with pytest.raises(BrowserError, match="public profile identifier.*Set LINKEDIN_USERNAME to your login email or phone"):
        login_credentials(headless=True, profile="example-person")

    with pytest.raises(BrowserError, match="different profile"):
        login_credentials(headless=False, profile="another-person")


@pytest.mark.parametrize("identifier", ["https://unrelated.example/in/example-person/", "https://www.linkedin.com/company/example/"])
def test_username_rejects_unrecognized_urls(monkeypatch: MonkeyPatch, identifier: str) -> None:
    """
    Reject URLs outside the profile namespace without echoing environment values.

    Args:
        monkeypatch (MonkeyPatch): Supplies an unsupported identifier and password.
        identifier (str): URL that cannot identify a public profile.

    Returns:
        None: Validation reports the accepted formats without exposing the value or password.
    """
    monkeypatch.setenv("LINKEDIN_USERNAME", identifier)
    monkeypatch.setenv("LINKEDIN_PASSWORD", "synthetic-password")

    with pytest.raises(
        BrowserError, match="LINKEDIN_USERNAME must be a login email/phone, public username, or LinkedIn profile URL"
    ) as error:
        login_credentials(headless=True)

    assert identifier not in str(error.value)
    assert "synthetic-password" not in str(error.value)


def test_public_only_credentials_fail_before_browser(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Fail the reported CI setup before launching a browser or replacing a saved profile.

    Args:
        tmp_path (Path): Temporary configuration and accepted snapshot directory.
        monkeypatch (MonkeyPatch): Supplies a profile URL in the existing username variable.

    Returns:
        None: The error explains the required login secret and the prior capture remains intact.
    """
    monkeypatch.setenv("LINKEDIN_USERNAME", "https://www.linkedin.com/in/example-person/")
    monkeypatch.setenv("LINKEDIN_PASSWORD", "synthetic-password")
    path = tmp_path / "config.yaml"
    path.write_text("linkedin: {username: example-person}\n")
    snapshot = tmp_path / "data/profile.json"
    snapshot.parent.mkdir()
    snapshot.write_text("previous accepted snapshot")
    browser = MagicMock()
    monkeypatch.setattr("resumeme.linkedin.capture.profile._browser", browser)

    with pytest.raises(BrowserError, match="Set LINKEDIN_USERNAME to your login email or phone"):
        capture_profile(load_config(path), tmp_path, headless=True)

    browser.assert_not_called()
    assert snapshot.read_text() == "previous accepted snapshot"
