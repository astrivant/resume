"""
Cache remote illustrations using credential-free, bounded requests.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
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
from resume.linkedin.links import discover_profile_links, safe_url
from resume.models import Entry, Media

if TYPE_CHECKING:
    from pathlib import Path

    from urllib3.response import BaseHTTPResponse

    from resume.config import Config
    from resume.models import Profile

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

        # Include the configured delay on the first retry, matching browser and shell retry behavior.
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

        # A server can ask us to wait longer, but cannot extend the request beyond the operator's configured delay cap.
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

    # Reject mixed public/private DNS answers as well as explicit private hosts before issuing the HTTP request.
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

    # Follow redirects ourselves so each new target passes the same public-address checks and receives no accumulated cookies.
    for _ in range(6):
        _validate_remote(url)
        session.cookies.clear()

        with session.get(url, timeout=(timeout, timeout), stream=True, allow_redirects=False) as response:
            if response.is_redirect:
                url = urljoin(url, response.headers["Location"])
                continue

            response.raise_for_status()

            # Enforce the byte budget while streaming; Content-Length may be absent or untrustworthy.
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

    # Resume interrupted downloads from already recorded assets before contacting expiring remote image URLs.
    if image.path and project_path(root, image.path).is_file():
        return image

    body, _ = fetch_public(session, image.url, config.capture.page_timeout_seconds)

    # Decode and normalize formats at capture time so offline compilation only needs portable PNG inputs.
    with Image.open(BytesIO(body)) as source:
        source.load()
        converted = source.convert("RGBA")
        buffer = BytesIO()
        converted.save(buffer, format="PNG")

    content = buffer.getvalue()

    # Hash normalized bytes, not the remote URL, to deduplicate identical illustrations behind changing CDN references.
    digest = hashlib.sha256(content).hexdigest()
    path = project_path(root, config.output.assets) / f"{digest}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return evolve(image, path=path.relative_to(root).as_posix())


def _preview(url: str, session: requests.Session, timeout: int) -> tuple[str, str, str]:
    """
    Inspect a final destination, page title, and preview image without recursively crawling.

    Args:
        url (str): Linked project destination.
        session (requests.Session): Credential-free HTTP client.
        timeout (int): Request timeout.

    Returns:
        tuple[str, str, str]: Final URL, observed page title, and absolute preview image URL; unavailable metadata is empty.
    """
    visited: set[str] = set()

    # LinkedIn short links can return an HTTP-200 exit page rather than a redirect; follow only its explicit external-site control.
    for _ in range(6):
        if url in visited:
            raise ValueError("LinkedIn short link points to a previously visited page.")

        visited.add(url)
        content, destination = fetch_public(session, url, timeout)

        # Direct downloads can resolve successfully without being web pages; avoid parsing binary data or inventing preview requests.
        if not re.search(rb"<(?:!doctype\s+html|html|head|meta|title|link)\b", content[:4096], re.IGNORECASE):
            return destination, "", ""

        soup = BeautifulSoup(content, "html.parser")
        host = urlsplit(destination).hostname or ""
        external = soup.select_one('a[data-tracking-control-name="external_url_click"][href]')

        if (host in {"lnkd.in", "linkedin.com"} or host.endswith(".linkedin.com")) and external:
            url = safe_url(str(external.get("href", "")), destination)

            if not url:
                raise ValueError("LinkedIn short link has an invalid external destination.")

            continue

        break
    else:
        raise ValueError("LinkedIn short link exceeded five exit pages.")

    title_meta = soup.select_one('meta[property="og:title"]') or soup.select_one('meta[name="twitter:title"]')
    title = str(title_meta.get("content", "")).strip() if title_meta else ""

    if not title and soup.title:
        title = soup.title.get_text(" ", strip=True)

    # Relative metadata belongs to the redirected page, including its explicit HTML base when present.
    base_node = soup.select_one("base[href]")
    base = safe_url(str(base_node.get("href", "")), destination) if base_node else destination
    base = base or destination

    # Prefer a project's own preview image, then its icon; stop at this page instead of recursively crawling links.
    for selector in ('meta[property="og:image"]', 'meta[name="twitter:image"]', 'link[rel~="icon"]'):
        meta = soup.select_one(selector)

        if meta:
            image = safe_url(str(meta.get("href" if meta.name == "link" else "content", "")), base)

            if image:
                return destination, " ".join(title.split()), image

    return destination, " ".join(title.split()), safe_url("/favicon.ico", destination)


def cache_media(profile: Profile, config: Config, root: Path) -> Profile:
    """
    Discover prose links, inspect their destinations, and cache illustrations with explicit failure warnings.

    Args:
        profile (Profile): Captured content with remote image references.
        config (Config): Media settings.
        root (Path): Configuration directory.

    Returns:
        Profile: Snapshot retaining original text and URLs, observed link metadata, local assets, and incompleteness warnings.
    """

    # Apply the same discovery to new captures and existing snapshots, including role-level ownership for later job exclusions.
    profile = discover_profile_links(profile)
    warnings = list(profile.warnings)

    # Cache outcomes across the whole capture because logos and project links recur in several sections and grouped roles.
    downloaded: dict[str, Media] = {}
    previews: dict[str, tuple[str, str, str] | None] = {}

    with requests.Session() as session:
        # Never inherit .netrc credentials, browser cookies, or environment proxies.
        session.trust_env = False
        session.headers["User-Agent"] = "resume/0.1 (profile owner media export)"

        # Retry only read requests and transient HTTP statuses; authentication and parsing failures stay visible.
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
                        # Preserve the unresolved reference and warn once; repeated appearances must not trigger repeated downloads.
                        warnings.append(f"Image unavailable ({item.alt or urlsplit(item.url).hostname}): {type(error).__name__}")
                        downloaded[item.url] = item

                # Reuse the bytes while keeping this occurrence's own accessible label and link destination.
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
            links = list(entry.links)

            if previews_enabled and config.capture.fetch_link_previews:
                for index, link in enumerate(links):
                    # Keep LinkedIn navigation out of unauthenticated requests; external short links remain eligible for resolution.
                    host = urlsplit(link.url).hostname or ""

                    if host == "linkedin.com" or host.endswith(".linkedin.com"):
                        continue

                    if link.url not in previews:
                        try:
                            previews[link.url] = _preview(link.url, session, config.capture.page_timeout_seconds)
                        except (requests.RequestException, OSError, ValueError) as error:
                            warnings.append(f"Link preview unavailable ({link.label}): {type(error).__name__}")
                            previews[link.url] = None

                    metadata = previews[link.url]

                    if metadata is not None:
                        destination, title, image_url = metadata
                        links[index] = evolve(link, resolved_url=destination, title=title)

                        # Replace legacy previews that captured LinkedIn's exit-page icon instead of the actual project.
                        if host == "lnkd.in" and destination != link.url:
                            candidates = [
                                item
                                for item in candidates
                                if not (item.link == link.url and urlsplit(item.url).hostname == "static.licdn.com")
                            ]

                        # Retain original associations for grouped-job filtering and reuse an illustration already captured for this link.
                        if image_url and not any(item.link == link.url for item in candidates):
                            candidates.append(Media(url=image_url, alt=title or link.label, link=link.url))

            # Record assets on individual roles too, so later exclusions can remove their media without losing shared logos.
            return evolve(
                entry,
                links=links,
                images=images(candidates),
                positions=[entry_media(position, previews_enabled) for position in entry.positions],
            )

        intro = entry_media(Entry(paragraphs=profile.intro, links=profile.links, images=profile.images), True)

        # Contact URLs remain clickable references; fetching previews for them would turn contact metadata into extra browsing.
        sections = [
            evolve(section, entries=[entry_media(entry, section.key != "contact") for entry in section.entries])
            for section in profile.sections
        ]

    return evolve(profile, links=intro.links, images=intro.images, sections=sections, warnings=warnings)
