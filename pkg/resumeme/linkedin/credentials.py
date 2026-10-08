"""
Separate public profile identifiers from private LinkedIn login credentials.
"""

from __future__ import annotations

import os
import re
from urllib.parse import urlsplit

from resumeme.exceptions import BrowserError, ConfigurationError

__all__ = ["login_credentials", "profile_username"]

_SLUG = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{1,99}")
_EMAIL = re.compile(r"[^\s@/]+@[^\s@/]+")
_PHONE = re.compile(r"\+?[0-9(). -]+")


def profile_username(value: str) -> str:
    """
    Normalize a public username or LinkedIn profile URL without fetching remote data.

    Args:
        value (str): Public slug or HTTP(S) profile URL, optionally without the scheme.

    Returns:
        str: Profile slug, excluding URL tracking parameters and fragments.

    Raises:
        ConfigurationError: The input is not a supported public profile identifier.
    """
    value = value.strip()

    if _SLUG.fullmatch(value):
        return value

    # Only recognized profile URLs become slugs; credentials, ports, and unrelated LinkedIn routes are not identities.
    try:
        location = urlsplit(value if "://" in value else "https://" + value.removeprefix("//"))
    except ValueError as error:
        raise ConfigurationError("Use a valid LinkedIn profile URL.") from error
    match = re.fullmatch(r"/in/([A-Za-z0-9][A-Za-z0-9_-]{1,99})/?", location.path)

    if location.scheme in {"http", "https"} and re.fullmatch(r"(?:(?:www|[a-z]{2})\.)?linkedin\.com", location.netloc.casefold()) and match:
        return match.group(1)

    raise ConfigurationError("Use a LinkedIn profile username or an HTTP(S) linkedin.com/in/<username>/ URL.")


def _is_login(value: str) -> bool:
    """
    Distinguish email and phone identifiers from public profile slugs and URLs.

    Args:
        value (str): Trimmed environment value, never written to logs.

    Returns:
        bool: The identifier has email or phone syntax; account validity remains LinkedIn's responsibility.
    """
    return bool(_EMAIL.fullmatch(value) or (_PHONE.fullmatch(value) and 7 <= sum(char.isdigit() for char in value) <= 15))


def login_credentials(*, headless: bool, profile: str | None = None) -> tuple[str, str]:
    """
    Detect login credentials or a public profile identity in the existing username variable.

    Args:
        headless (bool): Require an email/phone login; otherwise permit manual sign-in for public profile identifiers.
        profile (str | None): Configured profile identity to check against an optional public LINKEDIN_USERNAME.

    Returns:
        tuple[str, str]: Login email/phone and unchanged password, or two empty strings for interactive login.

    Raises:
        BrowserError: Login secrets are incomplete, identify a public profile only, or select a different configured owner.
    """
    public_or_login = os.environ.get("LINKEDIN_USERNAME", "").strip()
    password = os.environ.get("LINKEDIN_PASSWORD", "")

    # Keep YAML authoritative for profile selection so a stale environment cannot silently switch the captured owner.
    if public_or_login and not _is_login(public_or_login):
        try:
            public = profile_username(public_or_login)
        except ConfigurationError as error:
            raise BrowserError("LINKEDIN_USERNAME must be a login email/phone, public username, or LinkedIn profile URL.") from error

        if profile is not None and public.casefold() != profile_username(profile).casefold():
            raise BrowserError("LINKEDIN_USERNAME identifies a different profile from linkedin.username in the configuration.")

        if headless:
            raise BrowserError(
                "LINKEDIN_USERNAME is a public profile identifier, which LinkedIn cannot use to sign in. "
                "Set LINKEDIN_USERNAME to your login email or phone for --headless, or omit --headless to sign in manually. "
                "Keep the public profile username or URL in linkedin.username."
            )

        # A profile slug is not a login credential; interactive users can complete the real form without replaying a password.
        return "", ""

    if bool(public_or_login) != bool(password) or (headless and not public_or_login):
        raise BrowserError("Unattended login and partial credentials require LINKEDIN_USERNAME (login email/phone) and LINKEDIN_PASSWORD.")

    return public_or_login, password
