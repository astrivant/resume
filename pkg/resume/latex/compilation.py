"""
Compile generated LaTeX using the pinned TeX image or the toolchain bundled in the runtime container.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from importlib.resources import files
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING
from zipfile import ZipFile

from resume.config import project_path

if TYPE_CHECKING:
    from resume.config import Config

__all__ = ["compile_pdf", "tex_image"]


def tex_image() -> str:
    """
    Read the immutable compiler image used by local builds and CI.

    Returns:
        str: Docker image with its content digest.
    """

    # Package the compiler reference with the wheel so installed CLIs and source checkouts select the same toolchain.
    value: object = json.loads(files("resume.latex").joinpath("resources/toolchain.json").read_text(encoding="utf-8"))["tex_image"]

    if not isinstance(value, str):
        raise ValueError("The packaged TeX image reference is invalid.")

    return value


def compile_pdf(source: Path, config: Config, root: Path) -> Path:
    """
    Compile twice and atomically replace the PDF only after a successful build.

    Args:
        source (Path): Generated LaTeX source with adjacent image assets.
        config (Config): PDF destination.
        root (Path): Configuration directory.

    Returns:
        Path: Completed PDF.

    Raises:
        RuntimeError: Docker or pdfLaTeX fails; the previous PDF is preserved.
        ValueError: RESUME_TEX_BACKEND is neither docker nor local.
        subprocess.TimeoutExpired: A compiler pass exceeds two minutes.
    """

    # Host installs launch the isolated compiler image; the runtime container invokes its bundled binary without nested Docker.
    backend = os.environ.get("RESUME_TEX_BACKEND", "docker")

    if backend not in {"docker", "local"}:
        raise ValueError("RESUME_TEX_BACKEND must be docker or local.")

    source = source.resolve()
    destination = project_path(root, config.output.pdf)
    cache = root / ".cache/build"
    cache.mkdir(parents=True, exist_ok=True)

    # Keep intermediate output separate from the published PDF until both passes have completed successfully.
    with tempfile.TemporaryDirectory(dir=cache) as directory:
        output = Path(directory).resolve()

        # Ship the exact font files with the package: neither compiler backend needs a network or host font installation.
        font_archive = files("resume.latex").joinpath("resources/fonts/ebgaramond-texmf.zip").read_bytes()

        with ZipFile(BytesIO(font_archive)) as fonts:
            fonts.extractall(output / "texmf")

        command = (
            ["pdflatex"]
            if backend == "local"
            else [
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
                f"type=bind,source={source.parent},target=/data,readonly",
                "--mount",
                f"type=bind,source={output},target=/output",
                "--workdir",
                "/data",
                "--env",
                "SOURCE_DATE_EPOCH=946684800",
                "--env",
                "FORCE_SOURCE_DATE=1",
                "--env",
                "TEXMFHOME=/output/texmf",
                "--entrypoint",
                "pdflatex",
                tex_image(),
            ]
        )

        # Share compiler behavior across backends, including disabled shell escape and noninteractive failure reporting.
        command.extend(
            [
                "-no-shell-escape",
                "-halt-on-error",
                "-interaction=nonstopmode",
                "-file-line-error",
                f"-output-directory={output}" if backend == "local" else "-output-directory=/output",
                source.name,
            ]
        )

        # Fix embedded dates and run twice so references settle without introducing wall-clock differences into the PDF.
        environment = dict(os.environ, SOURCE_DATE_EPOCH="946684800", FORCE_SOURCE_DATE="1", TEXMFHOME=str(output / "texmf"))

        for number in (1, 2):
            result = subprocess.run(command, cwd=source.parent, env=environment, capture_output=True, text=True, timeout=120, check=False)
            log = cache / f"pdflatex-{number}.log"
            log.write_text(result.stdout + result.stderr, encoding="utf-8")

            if result.returncode:
                raise RuntimeError(f"PDF compilation failed; inspect {log}.")

        # A successful process exit alone is not enough; validate the expected artifact before atomically replacing the destination.
        compiled = output / source.with_suffix(".pdf").name

        if not compiled.is_file() or not compiled.read_bytes().startswith(b"%PDF-"):
            raise RuntimeError("The compiler did not produce a PDF.")

        destination.parent.mkdir(parents=True, exist_ok=True)
        pending = destination.with_suffix(".pending.pdf")
        shutil.copyfile(compiled, pending)
        pending.replace(destination)

    return destination
