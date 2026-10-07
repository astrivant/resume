"""
Add replaceable release provenance without reflowing the compiled resume.
"""

from __future__ import annotations

import re
from io import BytesIO
from urllib.parse import urlsplit

from pypdf import PdfWriter
from pypdf.annotations import Link
from pypdf.generic import ArrayObject, ContentStream, DecodedStreamObject, DictionaryObject, NameObject, NumberObject, TextStringObject

from resumeme.compiler.constants.footer import FOOTER_BASELINE, FOOTER_FONT_SIZE, FOOTER_GRAY, FOOTER_LEADING, FOOTER_MARGIN, FOOTER_NAME

__all__ = ["release_footer"]


def release_footer(pdf: bytes, release_url: str, fingerprint: str | None = None) -> bytes:
    """
    Place a light-gray release link and signing identity on the final page only.

    Args:
        pdf (bytes): Unsigned compiler output or a previously prepared working PDF.
        release_url (str): HTTPS release destination, or an empty string for a local build without a repository.
        fingerprint (str | None): DER SHA-256 public key identity; None labels the document as an unsigned working copy.

    Returns:
        bytes: Deterministic PDF preserving content, page count, metadata, and existing navigation.

    Raises:
        ValueError: Release identity is invalid or the document lacks a supported final page.
    """

    # The footer carries a public key identity, never the private key or a self-referential hash of the PDF.
    if fingerprint is not None and (not re.fullmatch(r"SHA256:[a-f0-9]{64}", fingerprint) or not release_url):
        raise ValueError("A release footer requires its HTTPS URL and the public key's SHA256 fingerprint.")

    location = urlsplit(release_url)

    if release_url and (
        location.scheme != "https"
        or not location.hostname
        or location.username is not None
        or location.password is not None
        or any(character.isspace() or ord(character) < 32 for character in release_url)
    ):
        raise ValueError("The release footer URL must use HTTPS without credentials or whitespace.")

    # Clone the entire document so named destinations, internal role links, and author metadata survive publication.
    writer = PdfWriter(clone_from=BytesIO(pdf))

    if not writer.pages:
        raise ValueError("Cannot add a release footer to a PDF without pages.")

    page = writer.pages[-1]

    if page.rotation or page.mediabox.left != 0 or page.mediabox.bottom != 0:
        raise ValueError("The resume footer requires an unrotated page with its origin at the lower left.")

    width = float(page.mediabox.width)
    label = "Release and verification" if fingerprint else "Releases"
    label_baseline = FOOTER_BASELINE + FOOTER_LEADING / (1 if fingerprint else 2)
    right = width - FOOTER_MARGIN

    # Two equal digest chunks keep the full identity readable in the half-page space beside the centered page number.
    if fingerprint:
        digest = fingerprint.removeprefix("SHA256:")
        lines = [
            (label, label_baseline),
            (f"Public key SHA256:{digest[:32]}", FOOTER_BASELINE),
            (digest[32:], FOOTER_BASELINE - FOOTER_LEADING),
        ]
    elif release_url:
        lines = [(label, label_baseline), ("Unsigned working copy", FOOTER_BASELINE - FOOTER_LEADING / 2)]
    else:
        lines = [("Unsigned working copy", FOOTER_BASELINE)]

    operations = [f"q {FOOTER_GRAY} g BT /FooterFont {FOOTER_FONT_SIZE} Tf"]

    # Courier's fixed 600-unit advance aligns both hash chunks at the right margin without another font dependency.
    for text, baseline in lines:
        left = right - len(text) * FOOTER_FONT_SIZE * 0.6
        operations.append(f"1 0 0 1 {left:.3f} {baseline} Tm ({text}) Tj")

    operations.append("ET Q")
    form = DecodedStreamObject()
    form.set_data("\n".join(operations).encode("ascii"))
    form.update(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Form"),
            NameObject("/BBox"): page.mediabox,
            NameObject("/Resources"): DictionaryObject(
                {
                    NameObject("/Font"): DictionaryObject(
                        {
                            NameObject("/FooterFont"): DictionaryObject(
                                {
                                    NameObject("/Type"): NameObject("/Font"),
                                    NameObject("/Subtype"): NameObject("/Type1"),
                                    NameObject("/BaseFont"): NameObject("/Courier"),
                                }
                            )
                        }
                    )
                }
            ),
        }
    )
    resources = page["/Resources"].get_object()
    assert isinstance(resources, DictionaryObject)
    objects = resources.setdefault(NameObject("/XObject"), DictionaryObject()).get_object()
    assert isinstance(objects, DictionaryObject)

    # A named form can be replaced in place: retries and tag releases remove the previous working-copy footer completely.
    if FOOTER_NAME not in objects:
        contents = page.get_contents()
        invocation = DecodedStreamObject()

        # A final image can leave the page translated or clipped; restore the page coordinate system before placing the footer.
        body = contents.get_data() if contents is not None else b""
        invocation.set_data(b"q\n" + body + f"\nQ\nq {FOOTER_NAME} Do Q\n".encode("ascii"))
        page.replace_contents(ContentStream(invocation, writer))

    # PDF streams must be indirect objects; the named resource avoids painting over stale text on later releases.
    objects[NameObject(FOOTER_NAME)] = writer._add_object(form)
    annotations = page.get("/Annots", ArrayObject())
    page[NameObject("/Annots")] = ArrayObject(annotation for annotation in annotations if annotation.get_object().get("/NM") != FOOTER_NAME)

    if release_url:
        annotation = Link(
            rect=(right - len(label) * FOOTER_FONT_SIZE * 0.6, label_baseline - 2, right, label_baseline + FOOTER_FONT_SIZE),
            url=release_url,
        )
        annotation[NameObject("/NM")] = TextStringObject(FOOTER_NAME)
        annotation[NameObject("/F")] = NumberObject(4)
        writer.add_annotation(len(writer.pages) - 1, annotation)

    # Keep the same identity machine-readable; timestamps are deliberately absent so retry output is reproducible.
    writer.add_metadata({"/ResumemeReleaseURL": release_url, "/ResumemePublicKey": fingerprint or ""})
    writer.compress_identical_objects(remove_duplicates=False, remove_unreferenced=True)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()
