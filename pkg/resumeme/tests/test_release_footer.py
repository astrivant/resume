"""
Verify release provenance is visible, repeatable, and preserves the tagged document.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Link
from pypdf.generic import ContentStream, DecodedStreamObject, DictionaryObject, NameObject

from resumeme.compiler.backends.pdf import release_footer
from resumeme.config import Ownership
from resumeme.linkedin.identity import release_destination
from resumeme.signing import public_key_fingerprint

if TYPE_CHECKING:
    from pypdf import PageObject
    from pytest import MonkeyPatch


def _document(pages: int, width: float = 612, height: float = 792) -> bytes:
    """
    Build a small resume substitute with real text and navigation.

    Args:
        pages (int): Document length, including the single-page base case.
        width (float): Paper width in PDF points.
        height (float): Paper height in PDF points.

    Returns:
        bytes: Valid PDF containing unique body text on each page and a named destination.
    """
    writer = PdfWriter()
    writer.add_metadata({"/Title": "Selected resume", "/Author": "Fixture owner"})

    for number in range(pages):
        page = writer.add_blank_page(width=width, height=height)
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {
                        NameObject("/Body"): DictionaryObject(
                            {
                                NameObject("/Type"): NameObject("/Font"),
                                NameObject("/Subtype"): NameObject("/Type1"),
                                NameObject("/BaseFont"): NameObject("/Times-Roman"),
                            }
                        )
                    }
                )
            }
        )
        body = DecodedStreamObject()
        body.set_data(f"BT /Body 10 Tf 54 700 Td (Selected body on page {number + 1}.) Tj ET".encode("ascii"))
        page.replace_contents(ContentStream(body, writer))
        writer.add_annotation(number, Link(rect=(54, 700, 180, 710), url="https://example.org/project"))

    writer.add_named_destination("experience", pages - 1)
    writer.add_annotation(0, Link(rect=(54, 680, 180, 690), target_page_index=pages - 1))
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _annotations(page: PageObject) -> list[DictionaryObject]:
    """
    Resolve page annotations while checking the library's generic object boundary.

    Args:
        page (PageObject): Page containing fixture links and optional release navigation.

    Returns:
        list[DictionaryObject]: Resolved annotation dictionaries in document order.
    """
    assert page.annotations is not None
    result: list[DictionaryObject] = []

    for reference in page.annotations:
        annotation = reference.get_object()
        assert isinstance(annotation, DictionaryObject)
        result.append(annotation)

    return result


@pytest.mark.parametrize("pages", [1, 3])
@pytest.mark.parametrize("paper", [(612, 792), (595.28, 841.89)])
def test_footer_preserves_content_navigation_and_paper(pages: int, paper: tuple[float, float]) -> None:
    """
    Limit the new footer to the last page without changing body text or link destinations.

    Args:
        pages (int): Single-page and multipage resume lengths.
        paper (tuple[float, float]): Letter and A4 dimensions.

    Returns:
        None: Both working and release PDFs retain all original document content and navigation.
    """
    original = _document(pages, *paper)
    working = release_footer(original, "https://github.com/owner/fork/releases")
    url = "https://github.com/owner/fork/releases/tag/resume-2026-10"
    fingerprint = "SHA256:" + "a" * 64
    signed = release_footer(working, url, fingerprint)
    reader = PdfReader(BytesIO(signed))
    before = PdfReader(BytesIO(original))
    assert len(reader.pages) == pages
    assert reader.metadata is not None
    assert reader.metadata.title == "Selected resume"
    assert reader.metadata.author == "Fixture owner"
    assert reader.get_destination_page_number(reader.named_destinations["experience"]) == pages - 1

    for number, page in enumerate(reader.pages):
        assert page.mediabox == before.pages[number].mediabox
        body = page.extract_text()
        assert body.count(before.pages[number].extract_text()) == 1
        assert body.replace("\n", "").count(fingerprint) == int(number == pages - 1)
        assert "Unsigned working copy" not in body
        annotations = _annotations(page)
        assert annotations[0].get("/A", {})["/URI"] == "https://example.org/project"
        assert len(annotations) == len(_annotations(before.pages[number])) + int(number == pages - 1)

    assert _annotations(reader.pages[0])[1].get("/Dest", [])[0].get_object() == reader.pages[-1]
    footer_link = _annotations(reader.pages[-1])[-1]
    assert footer_link.get("/A", {})["/URI"] == url
    assert float(footer_link.get("/Rect", [])[0]) > paper[0] / 2
    assert float(footer_link.get("/Rect", [])[2]) < paper[0] - 50
    assert float(footer_link.get("/Rect", [])[3]) < 45

    # Retries must keep one footer and identical bytes; the signed source is never rebuilt from current profile inputs.
    assert release_footer(working, url, fingerprint) == signed
    assert release_footer(signed, url, fingerprint) == signed


def test_footer_after_a_final_image_uses_page_coordinates() -> None:
    """
    Keep the footer at the page bottom when the document ends with translated graphics.

    Returns:
        None: Final artwork cannot translate the provenance outside its link annotation.
    """
    writer = PdfWriter(clone_from=BytesIO(_document(1)))
    page = writer.pages[-1]
    contents = page.get_contents()
    assert contents is not None
    artwork = DecodedStreamObject()

    # pdfLaTeX can leave this translation after an image when no subsequent text resets its graphics coordinates.
    artwork.set_data(contents.get_data() + b"\n1 0 0 1 117 275 cm\n")
    page.replace_contents(ContentStream(artwork, writer))
    output = BytesIO()
    writer.write(output)
    reader = PdfReader(BytesIO(release_footer(output.getvalue(), "https://example.org/releases")))
    matrices: list[list[float]] = []

    def locate(text: str, cm: list[float], tm: list[float], font: DictionaryObject | None, size: float) -> None:
        """
        Record the effective graphics coordinates used by the working-copy footer.

        Args:
            text (str): Extracted text fragment.
            cm (list[float]): Current graphics transformation matrix.
            tm (list[float]): Text transformation matrix.
            font (DictionaryObject | None): Resolved font resources.
            size (float): Font size in points.

        Returns:
            None: Footer matrices are collected for the placement assertion.
        """
        if "Unsigned working copy" in text:
            matrices.append(cm)

    reader.pages[-1].extract_text(visitor_text=locate)
    assert matrices
    assert all(matrix == [1, 0, 0, 1, 0, 0] for matrix in matrices)


def test_key_rotation_replaces_old_footer() -> None:
    """
    Remove the prior release identity rather than painting a new key over hidden text.

    Returns:
        None: Searchable content and annotations contain only the current release identity.
    """
    first_key = "SHA256:" + "a" * 64
    next_key = "SHA256:" + "b" * 64
    first = release_footer(_document(1), "https://example.org/first", first_key)
    rotated = release_footer(first, "https://example.org/next", next_key)
    reader = PdfReader(BytesIO(rotated))
    text = reader.pages[-1].extract_text().replace("\n", "")
    assert first_key not in text
    assert text.count(next_key) == 1
    assert len(_annotations(reader.pages[-1])) == 3
    assert reader.metadata is not None
    assert reader.metadata.get("/ResumemePublicKey") == next_key


@pytest.mark.parametrize(
    "url,fingerprint",
    [
        ("", "SHA256:" + "a" * 64),
        ("https://example.org", "private signing material"),
        ("http://example.org", None),
        ("https://user:secret@example.org", None),
        ("https://example.org/\ninjected", None),
    ],
)
def test_invalid_release_identity_is_rejected(url: str, fingerprint: str | None) -> None:
    """
    Reject invalid identity before reading or modifying the source PDF.

    Args:
        url (str): Release destination under validation.
        fingerprint (str | None): Optional supplied public key identity.

    Returns:
        None: Invalid identity cannot enter an artifact.
    """
    with pytest.raises(ValueError):
        release_footer(b"not read", url, fingerprint)


def test_local_build_without_origin_has_no_invented_release(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Keep installed CLI builds usable outside a Git checkout.

    Args:
        tmp_path (Path): Directory without a repository or origin remote.
        monkeypatch (MonkeyPatch): Clear the runner's optional repository identity.

    Returns:
        None: Local output is visibly unsigned without an unrelated upstream release link.
    """
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    url = release_destination(Ownership(), tmp_path, allow_missing=True)
    assert url == ""
    result = PdfReader(BytesIO(release_footer(_document(1), url)))
    assert result.pages[-1].extract_text().endswith("Unsigned working copy")
    assert len(_annotations(result.pages[-1])) == 2


def test_release_metadata_embeds_the_actual_public_identity(tmp_path: Path) -> None:
    """
    Bind the staged PDF to the actual public key and exact publishing tag before signing.

    Args:
        tmp_path (Path): Isolated artifacts and disposable test-only signing key.

    Returns:
        None: The PDF, fingerprint attachment, and provenance agree and reruns produce identical bytes.
    """
    private = tmp_path / "fixture.key"
    public = tmp_path / "cosign.pub"
    subprocess.run(["openssl", "genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-256", "-out", str(private)], check=True)
    subprocess.run(["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)], check=True)
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(release_footer(_document(2), "https://example.org/short-link"))
    tag = "resume/2026-10+é"
    environment = dict(os.environ, SOURCE_SHA="a" * 40, GITHUB_REPOSITORY="owner/fork", RELEASE_TAG=tag)
    command = [sys.executable, "scripts/release/metadata.py", str(tmp_path)]
    root = Path(__file__).resolve().parents[3]
    subprocess.run(command, cwd=root, env=environment, check=True)
    fingerprint = public_key_fingerprint(public)
    metadata = json.loads((tmp_path / "source.json").read_text())
    assert metadata["source_commit"] == "a" * 40
    assert metadata["public_key_sha256_der"] == fingerprint.removeprefix("SHA256:")
    assert metadata["release_url"] == f"https://github.com/owner/fork/releases/tag/{quote(tag, safe='')}"
    assert (tmp_path / "key-fingerprint.txt").read_text() == fingerprint + "\n"
    reader = PdfReader(pdf)
    assert fingerprint in reader.pages[-1].extract_text().replace("\n", "")
    assert _annotations(reader.pages[-1])[-1].get("/A", {})["/URI"] == metadata["release_url"]
    prepared = pdf.read_bytes()
    subprocess.run(command, cwd=root, env=environment, check=True)
    assert pdf.read_bytes() == prepared
