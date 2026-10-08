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
    Resolve explicit login credentials while preserving legacy email-based secrets.

    Args:
        headless (bool): Require a complete unattended login; otherwise permit no credentials for manual sign-in.
        profile (str | None): Configured profile identity to check against an optional public LINKEDIN_USERNAME.

    Returns:
        tuple[str, str]: Login email/phone and unchanged password, or two empty strings for interactive login.

    Raises:
        BrowserError: Login secrets are incomplete, identify a public profile only, or select a different configured owner.
    """
    public_or_login = os.environ.get("LINKEDIN_USERNAME", "").strip()
    explicit_login = os.environ.get("LINKEDIN_LOGIN", "").strip()
    password = os.environ.get("LINKEDIN_PASSWORD", "")
    login = explicit_login or public_or_login

    # Keep YAML authoritative for profile selection so a stale environment cannot silently switch the captured owner.
    if public_or_login and not _is_login(public_or_login):
        try:
            public = profile_username(public_or_login)
        except ConfigurationError as error:
            raise BrowserError("LINKEDIN_USERNAME must be a login email/phone, public username, or LinkedIn profile URL.") from error

        if profile is not None and public.casefold() != profile_username(profile).casefold():
            raise BrowserError("LINKEDIN_USERNAME identifies a different profile from linkedin.username in the configuration.")

        if not explicit_login:
            if headless or password:
                raise BrowserError(
                    "LINKEDIN_USERNAME is a public profile identifier, which LinkedIn cannot use to sign in. "
                    "Set LINKEDIN_LOGIN to your login email or phone, or replace LINKEDIN_USERNAME with that login identifier. "
                    "Keep the public profile username or URL in linkedin.username."
                )

            return "", ""

    if login and not _is_login(login):
        raise BrowserError("LINKEDIN_LOGIN must be your login email or phone, not a public profile username or URL.")

    if bool(login) != bool(password) or (headless and not login):
        raise BrowserError(
            "Unattended login and partial credentials require LINKEDIN_LOGIN (or legacy LINKEDIN_USERNAME) and LINKEDIN_PASSWORD."
        )

    return login, password
