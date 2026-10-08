"""
Package the accepted PDF and a small static landing page for GitHub Pages.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

from jinja2 import Environment, StrictUndefined
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from resumeme.compiler.passes.themes import resolve_style
from resumeme.config import project_path

if TYPE_CHECKING:
    from resumeme.compiler.asts.profile import Profile
    from resumeme.config import Config

__all__ = ["build_site"]


def build_site(profile: Profile, config: Config, root: Path, repository: str) -> Path:
    """
    Prepare an isolated static site containing the existing PDF and escaped public identity.

    Args:
        profile (Profile): Captured identity belonging to the configured LinkedIn account.
        config (Config): PDF location, site subdirectory, introduction, and presentation preferences.
        root (Path): Configuration directory containing the accepted PDF.
        repository (str): Publishing GitHub owner/repository for the signed releases link.

    Returns:
        Path: Generated index.html beneath .cache/pages, the directory uploaded as a Pages artifact.

    Raises:
        ValueError: Ownership, repository, capture completeness, or PDF content is invalid.
        OSError: The accepted PDF cannot be read or the generated site cannot be written.
    """
    if profile.username.casefold() != config.linkedin.username.casefold() or profile.warnings:
        raise ValueError("Pages requires a complete profile belonging to the configured LinkedIn username.")

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+", repository) or repository.split("/")[-1] in {".", ".."}:
        raise ValueError("Pages requires the publishing GitHub repository as OWNER/REPO.")

    # Use the accepted document verbatim, including its existing layout and footer; site generation never rebuilds it.
    pdf = project_path(root, config.output.pdf)

    if not pdf.read_bytes().startswith(b"%PDF-"):
        raise ValueError("Pages requires a nonempty PDF. Build the resume before generating the site.")

    try:
        if not PdfReader(pdf).pages:
            raise ValueError("Pages requires a PDF containing at least one page.")
    except PdfReadError as error:
        raise ValueError("Pages could not read the PDF. Rebuild the resume before generating the site.") from error

    name = profile.name.strip() or profile.username
    style = resolve_style(config.style)
    template = Environment(autoescape=True, undefined=StrictUndefined, keep_trailing_newline=True).from_string(
        files("resumeme.github").joinpath("resources/index.html.j2").read_text(encoding="utf-8")
    )
    document = template.render(
        name=name,
        introduction=config.readme.introduction or "My résumé, kept current from LinkedIn.",
        linkedin_url=f"https://www.linkedin.com/in/{quote(profile.username, safe='')}/",
        github_url=f"https://github.com/{quote(config.github.username, safe='')}" if config.github.username else None,
        releases_url=f"https://github.com/{repository}/releases",
        style=style,
    )
    destination = project_path(root, ".cache/pages")
    destination.parent.mkdir(parents=True, exist_ok=True)
    index_path = config.pages.path.strip("/") + "/index.html" if config.pages.path != "/" else "index.html"

    # Build in scratch space first, then replace only our generated site so changing paths cannot leave an old PDF online.
    with tempfile.TemporaryDirectory(dir=destination.parent) as directory:
        staging = Path(directory)
        index = project_path(staging, index_path)
        index.parent.mkdir(parents=True, exist_ok=True)
        index.write_text(document, encoding="utf-8")
        shutil.copyfile(pdf, index.with_name("resume.pdf"))

        if destination.exists():
            shutil.rmtree(destination)

        shutil.copytree(staging, destination)

    return destination / index_path
