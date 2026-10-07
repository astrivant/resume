"""
Cache remote illustrations using credential-free, bounded requests.
"""

from __future__ import annotations

import hashlib
import ipaddress
import socket
import sys
import time
from io import BytesIO
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlsplit

import requests
from attrs import evolve
from bs4 import BeautifulSoup
from PIL import Image, UnidentifiedImageError
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from resume.config import project_path
from resume.linkedin.parsing import safe_url

if TYPE_CHECKING:
    from pathlib import Path

    from urllib3.response import BaseHTTPResponse

    from resume.config import Config
    from resume.models import Entry, Media, Profile

__all__ = ["cache_media", "fetch_public"]

_MAX_BYTES = 10 * 1024 * 1024


class _ExponentialRetry(Retry):
    """
    Apply the initial delay to the first retry and cap server-provided delays too.
    """

    def get_backoff_time(self) -> float:
        """
        Double the initial delay after each successive failed attempt.

        Returns:
            float: Exponential delay bounded by the configured maximum.
        """
        return float(min(self.backoff_factor * 2 ** max(0, len(self.history) - 1), self.backoff_max))

    def sleep(self, response: BaseHTTPResponse | None = None) -> None:
        """
        Respect Retry-After while keeping retries within the configured delay cap.

        Args:
            response (BaseHTTPResponse | None): Response optionally containing Retry-After.

        Returns:
            None: The bounded retry delay has elapsed.
        """
        retry_after = self.get_retry_after(response) if self.respect_retry_after_header and response else None
        delay = min(max(self.get_backoff_time(), retry_after or 0), self.backoff_max)
        print(f"HTTP failure: retrying attempt {len(self.history) + 1} in {delay:g}s.", file=sys.stderr, flush=True)
        time.sleep(delay)


def _validate_remote(url: str) -> None:
    """
    Reject local network targets before each request, including redirect targets.

    Args:
        url (str): Remote image or preview URL.

    Returns:
        None: The URL resolves exclusively to public addresses.

    Raises:
        ValueError: The URL is not a public HTTP destination.
        OSError: DNS resolution fails.
    """
    parsed = urlsplit(url)
    if not safe_url(url) or parsed.hostname is None or parsed.port not in {None, 80, 443}:
        raise ValueError("Media references must be public HTTP(S) URLs on standard ports.")
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(address[4][0]).is_global for address in addresses):
        raise ValueError("Media references cannot target local or private networks.")


def fetch_public(session: requests.Session, url: str, timeout: int) -> tuple[bytes, str]:
    """
    Fetch a bounded public resource, validating every redirect without credentials.

    Args:
        session (requests.Session): Dedicated unauthenticated media session.
        url (str): Resource URL.
        timeout (int): Connect and read timeout in seconds.

    Returns:
        tuple[bytes, str]: Response body and final URL for relative references.

    Raises:
        ValueError: The response is too large or exceeds the redirect limit.
        requests.RequestException: The request or HTTP status fails.
    """
    for _ in range(6):
        _validate_remote(url)
        session.cookies.clear()
        with session.get(url, timeout=(timeout, timeout), stream=True, allow_redirects=False) as response:
            if response.is_redirect:
                url = urljoin(url, response.headers["Location"])
                continue
            response.raise_for_status()
            body = bytearray()
            for chunk in response.iter_content(65536):
                body.extend(chunk)
                if len(body) > _MAX_BYTES:
                    raise ValueError("Remote resource exceeds the 10 MiB download limit.")
            return bytes(body), url
    raise ValueError("Remote resource exceeded five redirects.")


def _download(image: Media, session: requests.Session, root: Path, config: Config) -> Media:
    """
    Normalize an illustration to a content-addressed PNG understood by pdfLaTeX.

    Args:
        image (Media): Original image reference.
        session (requests.Session): Credential-free HTTP client.
        root (Path): Project root.
        config (Config): Download and output settings.

    Returns:
        Media: Reference with a portable local image path, reusing an explicitly recorded asset when present.
    """
    if image.path and project_path(root, image.path).is_file():
        return image
    body, _ = fetch_public(session, image.url, config.capture.page_timeout_seconds)
    with Image.open(BytesIO(body)) as source:
        source.load()
        converted = source.convert("RGBA")
        buffer = BytesIO()
        converted.save(buffer, format="PNG")
    content = buffer.getvalue()
    digest = hashlib.sha256(content).hexdigest()
    path = project_path(root, config.output.assets) / f"{digest}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return evolve(image, path=path.relative_to(root).as_posix())


def _preview(url: str, session: requests.Session, timeout: int) -> str:
    """
    Find a project's Open Graph image or site icon without recursively crawling.

    Args:
        url (str): Linked project destination.
        session (requests.Session): Credential-free HTTP client.
        timeout (int): Request timeout.

    Returns:
        str: Resolved preview image or conventional favicon URL.
    """
    content, destination = fetch_public(session, url, timeout)
    soup = BeautifulSoup(content, "html.parser")
    meta = soup.select_one('meta[property="og:image"], meta[name="twitter:image"]')
    if meta:
        return safe_url(str(meta.get("content", "")), destination)
    icon = soup.select_one('link[rel~="icon"]')
    return safe_url(str(icon.get("href", "/favicon.ico")) if icon else "/favicon.ico", destination)


def cache_media(profile: Profile, config: Config, root: Path) -> Profile:
    """
    Download profile images and linked previews, retaining failures as warnings.

    Args:
        profile (Profile): Captured content with remote image references.
        config (Config): Media settings.
        root (Path): Configuration directory.

    Returns:
        Profile: Snapshot with local assets and explicit incompleteness warnings.
    """
    from resume.models import Media

    warnings = list(profile.warnings)
    downloaded: dict[str, Media] = {}
    previews: dict[str, str] = {}

    with requests.Session() as session:
        # Never inherit .netrc credentials, browser cookies, or environment proxies.
        session.trust_env = False
        session.headers["User-Agent"] = "resume/0.1 (profile owner media export)"
        policy = _ExponentialRetry(
            total=config.capture.retry_attempts - 1,
            backoff_factor=config.capture.retry_backoff_seconds,
            backoff_max=config.capture.retry_max_backoff_seconds,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,
            retry_after_max=config.capture.retry_max_backoff_seconds,
        )
        session.mount("https://", HTTPAdapter(max_retries=policy))
        session.mount("http://", HTTPAdapter(max_retries=policy))

        def images(items: list[Media]) -> list[Media]:
            """
            Reuse successful downloads across sections and retain failed references.

            Args:
                items (list[Media]): Image references in display order.

            Returns:
                list[Media]: References with local paths where available.
            """
            result: list[Media] = []
            for item in items:
                if item.url not in downloaded:
                    try:
                        downloaded[item.url] = _download(item, session, root, config)
                    except (requests.RequestException, OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as error:
                        warnings.append(f"Image unavailable ({item.alt or urlsplit(item.url).hostname}): {type(error).__name__}")
                        downloaded[item.url] = item
                result.append(evolve(item, path=downloaded[item.url].path))
            return result

        def entry_media(entry: Entry, previews_enabled: bool) -> Entry:
            """
            Add previews for external references, preserving their link association.

            Args:
                entry (Entry): Profile entry.
                previews_enabled (bool): Whether this section represents content eligible for project previews.

            Returns:
                Entry: Entry with locally cached media.
            """
            candidates = list(entry.images)
            if previews_enabled and config.capture.fetch_link_previews:
                for link in entry.links:
                    host = urlsplit(link.url).hostname or ""
                    if host == "linkedin.com" or host.endswith(".linkedin.com") or any(item.link == link.url for item in candidates):
                        continue
                    if link.url not in previews:
                        try:
                            previews[link.url] = _preview(link.url, session, config.capture.page_timeout_seconds)
                        except (requests.RequestException, OSError, ValueError) as error:
                            warnings.append(f"Link preview unavailable ({link.label}): {type(error).__name__}")
                            previews[link.url] = ""
                    if previews[link.url]:
                        candidates.append(Media(url=previews[link.url], alt=link.label, link=link.url))
            return evolve(
                entry,
                images=images(candidates),
                positions=[entry_media(position, previews_enabled) for position in entry.positions],
            )

        intro_images = images(profile.images)
        sections = [
            evolve(section, entries=[entry_media(entry, section.key != "contact") for entry in section.entries])
            for section in profile.sections
        ]
    return evolve(profile, images=intro_images, sections=sections, warnings=warnings)
