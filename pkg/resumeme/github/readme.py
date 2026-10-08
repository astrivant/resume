"""
Prepare a personal repository landing page from the verified resume publication.
"""

from __future__ import annotations

import hashlib
import html
import logging
import os
import posixpath
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

from PIL import Image
from pypdf import PdfReader

from resumeme.compiler.asts.profile import load_profile
from resumeme.compiler.backends.latex.compilation import tex_image
from resumeme.compiler.constants.escaping import PUNCTUATION
from resumeme.config import Ownership, project_path
from resumeme.exceptions import PublicationError
from resumeme.linkedin.identity import release_destination
from resumeme.visualization.branding import render_brew_badge

if TYPE_CHECKING:
    from datetime import date

    from resumeme.compiler.asts.profile import Profile
    from resumeme.config import Config

__all__ = ["PREVIEW_PATH", "personal_readme", "render_readme", "restore_readme", "stage_readme", "update_project_branding"]

PREVIEW_PATH = "docs/assets/resume-preview.png"
_BRANDING_START = "<!-- resumeme:branding:start -->"
_BRANDING_END = "<!-- resumeme:branding:end -->"
_BREW_BADGE_PATH = "docs/assets/branding/brew-date.svg"
_PUBLICATION_PATH = ".cache/publication"
_BOILERPLATE = (
    "My résumé, kept current from LinkedIn and published here as a PDF. Open the full document for every page and clickable links."
)


def update_project_branding(root: Path, config: Config, brewed_on: date, *, repository: str | None = None) -> None:
    """
    Refresh the local date badge and only the marked branding block of a project README.

    Args:
        root (Path): Publishing checkout containing an optional custom README.
        config (Config): Configured PDF destination for the badge link.
        brewed_on (date): UTC build date transported with the verified PDF artifact.
        repository (str | None): Publishing OWNER/REPO; defaults to Actions identity or the local Git origin.

    Returns:
        None: The SVG is refreshed; README text outside the opt-in branding markers is preserved exactly.

    Raises:
        PublicationError: Existing branding markers are invalid or no GitHub repository can be resolved.
    """
    path = root / "README.md"
    original = path.read_bytes().decode("utf-8") if path.exists() else ""
    updated = original

    # A custom README without our markers opts out of markup updates; never insert branding into an unrelated landing page.
    if _BRANDING_START in original or _BRANDING_END in original:
        if original.count(_BRANDING_START) != 1 or original.count(_BRANDING_END) != 1:
            raise PublicationError("README branding requires exactly one start marker and one end marker.")

        start, end = original.index(_BRANDING_START), original.index(_BRANDING_END)

        if end < start:
            raise PublicationError("README branding end marker must follow its start marker.")

        # Raw URLs work when package indexes render this Markdown without the checkout's relative asset paths.
        # Resolve the publishing repository independently of any inherited signing-release destination override.
        releases = release_destination(Ownership(repository=repository), root)
        repository = releases.removeprefix("https://github.com/").removesuffix("/releases")
        assets = f"https://raw.githubusercontent.com/{repository}/main/docs/assets/branding"
        pdf = "./" + quote(Path(config.output.pdf).as_posix(), safe="/")
        block = (
            f'{_BRANDING_START}\n<p align="left">\n'
            f'  <img src="{assets}/resumeme-logo.png" alt="resumeme: a coffee-stained LinkedIn mark" width="220"><br>\n'
            f'  <a href="{pdf}"><img src="{assets}/brew-date.svg" alt="Brew date: {brewed_on.isoformat()} (UTC)" '
            f'width="220" height="28"></a>\n</p>\n{_BRANDING_END}'
        )
        updated = original[:start] + block + original[end + len(_BRANDING_END) :]

    # Validate the managed block before replacing either file so malformed custom edits cannot leave a partial update.
    render_brew_badge(project_path(root, _BREW_BADGE_PATH), brewed_on)

    if updated != original:
        path.write_bytes(updated.encode("utf-8"))
        logging.getLogger(__name__).info("README branding updated", extra={"file.path": str(path)})


def personal_readme(config: Config, is_fork: bool) -> bool:
    """
    Resolve explicit overrides before GitHub's repository fork flag.

    Args:
        config (Config): Validated publication preferences.
        is_fork (bool): Whether the event's repository is a GitHub fork.

    Returns:
        bool: Whether publication manages the personal README and preview.
    """
    return config.readme.mode == "resume" or (config.readme.mode == "auto" and is_fork)


def _plain_text(value: str) -> str:
    """
    Normalize editorial punctuation without interpreting Markdown, HTML, or line breaks.

    Args:
        value (str): Captured name or configured introduction.

    Returns:
        str: Escaped text suitable for a Markdown heading, paragraph, or image label.
    """
    value = "".join(PUNCTUATION.get(character, character) for character in value)
    return re.sub(r"([\\`*_{}\[\]()#+.!|~>-])", r"\\\1", html.escape(" ".join(value.split())))


def render_readme(profile: Profile, config: Config, repository: str, pages: int) -> str:
    """
    Render shared boilerplate using the owner, document length, and public links.

    Args:
        profile (Profile): Validated captured identity, without exposing contact or headline fields.
        config (Config): Markdown and PDF destinations, optional GitHub account, and introduction.
        repository (str): Publishing GitHub owner/repository, independent of inherited release overrides.
        pages (int): Actual number of pages in the published working PDF.

    Returns:
        str: Complete UTF-8 Markdown with an absolute preview image URL and destination-relative document links.

    Raises:
        PublicationError: The snapshot owner, repository identifier, or page count is invalid.
    """

    # Repository identity comes from Actions, so forks never inherit the upstream owner's releases link.
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+", repository) or pages < 1:
        raise PublicationError("Personal README publication requires a GitHub owner/repository and a nonempty PDF.")

    if profile.username.casefold() != config.linkedin.username.casefold():
        raise PublicationError("The README snapshot belongs to another LinkedIn owner.")

    name = _plain_text(profile.name.strip() or profile.username)
    introduction = _plain_text(config.readme.introduction or _BOILERPLATE)

    # An example or nested landing page must resolve the same repository files as the root README.
    directory = Path(config.readme.output).parent.as_posix()
    targets = {
        name: quote(posixpath.relpath(value, directory), safe="/")
        for name, value in {
            "pdf": config.output.pdf,
            "config": "resumeme.config.yaml",
            "automation": "docs/automation.md",
        }.items()
    }

    # Keep media independent of the Markdown host and destination depth, following each fork's latest published PDF.
    preview = f"https://raw.githubusercontent.com/{repository}/main/{PREVIEW_PATH}"
    pdf = "./" + targets["pdf"]
    page_label = "page" if pages == 1 else "pages"
    links = [
        f"**[View résumé (PDF - {pages} {page_label})]({pdf})**",
        f"[LinkedIn](https://www.linkedin.com/in/{quote(profile.username, safe='')}/)",
    ]

    if config.github.username:
        links.append(f"[GitHub](https://github.com/{quote(config.github.username, safe='')})")

    links.append(f"[Releases & signatures](https://github.com/{repository}/releases)")

    # Keep adoption and maintenance details in documentation; the landing page is for readers of this person's resume.
    return (
        "<!-- Generated by resumeme. Edit readme in resumeme.config.yaml; mode: project preserves a custom README. -->\n\n"
        f"# {name} - Résumé\n\n"
        f"{introduction}\n\n"
        f"{' - '.join(links)}\n\n"
        f"[![First page of {name}'s résumé]({preview})]({pdf})\n\n"
        "*Preview of page 1. Click to open the complete PDF.*\n\n"
        "Built with [resumeme](https://github.com/astrivant/resume). "
        f"[Configuration]({targets['config']}) - [Automation]({targets['automation']}).\n"
    )


def _render_preview(pdf: Path, output: Path) -> None:
    """
    Rasterize only page one using Ghostscript from the pinned compiler image.

    Args:
        pdf (Path): Absolute staged PDF path mounted read-only.
        output (Path): Absolute scratch PNG destination on a writable bind mount.

    Returns:
        None: A full-page, 144 dpi RGB preview is written without variable metadata.

    Raises:
        subprocess.CalledProcessError: Docker or the rasterizer fails.
        subprocess.TimeoutExpired: Preview rendering takes longer than two minutes.
        OSError: The rasterizer output cannot be decoded as an image.
    """

    # Reuse the build's immutable toolchain; no host packages, network access, or browser credentials are needed.
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--platform",
            "linux/amd64",
            "--network=none",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--mount",
            f"type=bind,source={pdf},target=/input/resume.pdf,readonly",
            "--mount",
            f"type=bind,source={output.parent},target=/output",
            "--entrypoint",
            "gs",
            tex_image(),
            "-q",
            "-dSAFER",
            "-dBATCH",
            "-dNOPAUSE",
            "-dFirstPage=1",
            "-dLastPage=1",
            "-sDEVICE=png16m",
            "-r144",
            "-dTextAlphaBits=4",
            "-dGraphicsAlphaBits=4",
            f"-sOutputFile=/output/{output.name}",
            "/input/resume.pdf",
        ],
        check=True,
        timeout=120,
    )

    # Drop creation metadata so a rebuilt, unchanged PDF cannot cause a preview-only publication loop.
    with Image.open(output) as image:
        normalized = image.convert("RGB")
        normalized.info.clear()
        normalized.save(output, format="PNG", optimize=True)


def stage_readme(root: Path, config: Config, repository: str) -> None:
    """
    Add a complete README bundle to the existing cross-job PDF artifact.

    Args:
        root (Path): Checkout containing the configured captured profile and staged PDF.
        config (Config): Validated owner, paths, and personal README preferences.
        repository (str): Publishing GitHub owner/repository.

    Returns:
        None: Markdown, preview, and source PDF digest are staged under .cache/publication/readme.

    Raises:
        PublicationError: The snapshot has incomplete capture warnings or belongs to another owner.
        subprocess.CalledProcessError: Preview rendering fails; no new README bundle is published.
    """
    publication = project_path(root, _PUBLICATION_PATH)
    pdf = publication / "resume.pdf"
    profile = load_profile(project_path(root, config.output.profile), config.linkedin.username)

    if profile.warnings:
        raise PublicationError("Resolve incomplete capture warnings before publishing a personal README.")

    markdown = render_readme(profile, config, repository, len(PdfReader(pdf).pages))
    logging.getLogger(__name__).info("Preparing README preview", extra={"file.path": config.readme.output})

    # Build all files before replacing the bundle; deployment never reconstructs an image from different inputs.
    with tempfile.TemporaryDirectory(dir=publication) as directory:
        pending = Path(directory).resolve()
        _render_preview(pdf, pending / "resume-preview.png")
        (pending / "README.md").write_text(markdown, encoding="utf-8")
        (pending / "pdf.sha256").write_text(hashlib.sha256(pdf.read_bytes()).hexdigest() + "\n", encoding="ascii")
        shutil.copytree(pending, publication / "readme", dirs_exist_ok=True)


def restore_readme(root: Path, config: Config) -> tuple[str, str]:
    """
    Restore only the prepared landing page and image belonging to the staged PDF.

    Args:
        root (Path): Checkout receiving the verified publication artifact.
        config (Config): Configured input/output paths, checked for generated file collisions.

    Returns:
        tuple[str, str]: Explicit repository-relative files to stage with the PDF.

    Raises:
        PublicationError: The preview belongs to a different PDF or a configured path would be overwritten.
        OSError: The bundle is incomplete or the preview is not a valid PNG.
    """
    publication = project_path(root, _PUBLICATION_PATH)
    bundle = publication / "readme"

    # A partial download or stale bundle must fail before the publishing job replaces the previous landing page.
    digest = hashlib.sha256((publication / "resume.pdf").read_bytes()).hexdigest()

    if (bundle / "pdf.sha256").read_text(encoding="ascii").strip() != digest:
        raise PublicationError("The README preview belongs to a different PDF; rebuild the publication artifact.")

    markdown = (bundle / "README.md").read_bytes()
    preview = (bundle / "resume-preview.png").read_bytes()

    with Image.open(bundle / "resume-preview.png") as image:
        if image.format != "PNG":
            raise PublicationError("The README preview must be a PNG.")

        image.verify()

    paths = (config.readme.output, PREVIEW_PATH)
    destinations = tuple(project_path(root, path) for path in paths)
    inputs = [config.output.pdf, config.output.profile, config.output.tex, config.output.assets, "resumeme.config.yaml"]

    if config.template:
        inputs.append(config.template)

    if len(set(destinations)) != len(destinations) or any(
        destination == project_path(root, value) for destination in destinations for value in inputs
    ):
        raise PublicationError("Personal README paths must be distinct from configured inputs and outputs.")

    for destination, data in zip(destinations, (markdown, preview), strict=True):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)

    logging.getLogger(__name__).info("README publication restored", extra={"publication.files": list(paths)})
    return paths
