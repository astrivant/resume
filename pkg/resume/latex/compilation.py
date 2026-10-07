"""
Compile generated LaTeX in the pinned TeX Live container without network access.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING

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
        subprocess.TimeoutExpired: A compiler pass exceeds two minutes.
    """
    destination = project_path(root, config.output.pdf)
    cache = root / ".cache/build"
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=cache) as directory:
        output = Path(directory)
        command = [
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
            "--entrypoint",
            "pdflatex",
            tex_image(),
            "-no-shell-escape",
            "-halt-on-error",
            "-interaction=nonstopmode",
            "-file-line-error",
            "-output-directory=/output",
            source.name,
        ]
        for number in (1, 2):
            result = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
            log = cache / f"pdflatex-{number}.log"
            log.write_text(result.stdout + result.stderr, encoding="utf-8")
            if result.returncode:
                raise RuntimeError(f"PDF compilation failed; inspect {log}.")
        compiled = output / source.with_suffix(".pdf").name
        if not compiled.is_file() or not compiled.read_bytes().startswith(b"%PDF-"):
            raise RuntimeError("The compiler did not produce a PDF.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        pending = destination.with_suffix(".pending.pdf")
        shutil.copyfile(compiled, pending)
        pending.replace(destination)
    return destination
