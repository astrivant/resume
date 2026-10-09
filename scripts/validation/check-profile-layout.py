"""
Check compiled profile wrapping and skill-cloud alignment against synthetic layouts.
"""

from __future__ import annotations

import re
import tempfile
from datetime import timedelta
from itertools import pairwise
from pathlib import Path

from attrs import evolve
from PIL import Image
from pypdf import PdfReader
from pypdf.generic import DictionaryObject

from resumeme.compiler.asts.contributions import ContributionCalendar, ContributionDay, calendar_window
from resumeme.compiler.asts.profile import Entry, Link, Media, Profile, Section, Skill
from resumeme.compiler.backends.latex.compilation import compile_pdf
from resumeme.compiler.pipeline import render_profile
from resumeme.config import Config, GitHub, GitHubContributions, LinkedIn, Output, Style


def _rows(path: Path) -> list[tuple[int, str, float, float]]:
    """
    Read text baselines from the compiled document rather than inspecting template commands.

    Args:
        path (Path): Compiled synthetic PDF.

    Returns:
        list[tuple[int, str, float, float]]: Page number, text, and transformed baseline coordinates.
    """
    rows: list[tuple[int, str, float, float]] = []

    for page_number, page in enumerate(PdfReader(path).pages, 1):

        def record(
            text: str, cm: list[float], tm: list[float], font: DictionaryObject | None, size: float, page_index: int = page_number
        ) -> None:
            """
            Retain visible text positions after the page's drawing transformations.

            Args:
                text (str): Extracted text fragment.
                cm (list[float]): Current graphics matrix.
                tm (list[float]): Text matrix.
                font (DictionaryObject | None): Current font dictionary.
                size (float): Font size in points.
                page_index (int): Page number bound when this callback is created.

            Returns:
                None: Nonempty text fragments are appended to the surrounding result.
            """
            if text.strip():
                x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
                y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
                rows.append((page_index, text.strip(), x, y))

        page.extract_text(visitor_text=record)

    return rows


def _assert_cloud_centered(path: Path, cloud: Path) -> int:
    """
    Check the final skill image's drawn position against the physical page midpoint.

    Args:
        path (Path): Compiled fixture ending with its Skills section.
        cloud (Path): Generated cloud image used to distinguish it from profile artwork.

    Returns:
        int: One-based page number containing the verified cloud.

    Raises:
        AssertionError: The cloud is absent, duplicated, or displaced from the page center.
    """
    reader = PdfReader(path)
    page = reader.pages[-1]
    resources = page["/Resources"].get_object()
    assert isinstance(resources, DictionaryObject)
    objects = resources["/XObject"].get_object()
    assert isinstance(objects, DictionaryObject)

    with Image.open(cloud) as image:
        size = image.size

    # Synthetic portraits and banners have distinct dimensions; match the generated raster without relying on resource names.
    names = {
        str(name)
        for name, reference in objects.items()
        if isinstance(artwork := reference.get_object(), DictionaryObject)
        and artwork.get("/Subtype") == "/Image"
        and (artwork.get("/Width"), artwork.get("/Height")) == size
    }
    centers: list[float] = []

    def locate(operator: bytes, operands: list[object], cm: list[float], tm: list[float]) -> None:
        """
        Record image placement after applying the page's current graphics transformation.

        Args:
            operator (bytes): Parsed PDF operation.
            operands (list[object]): Operation arguments, including the image resource name.
            cm (list[float]): Current graphics transformation matrix.
            tm (list[float]): Text transformation matrix.

        Returns:
            None: Drawn image centers are collected for the alignment assertion.
        """
        if operator == b"Do" and str(operands[0]) in names:
            centers.append(cm[4] + (cm[0] + cm[2]) / 2)

    page.extract_text(visitor_operand_before=locate)
    expected = float(page.mediabox.left + page.mediabox.right) / 2
    assert len(centers) == 1, f"Expected one skill cloud, found {len(centers)}"
    assert abs(centers[0] - expected) < 0.5, f"Cloud center {centers[0]:.2f}pt differs from page center {expected:.2f}pt"
    return len(reader.pages)


def main() -> None:
    """
    Compile bounded layout fixtures using the selected installed PDF backend.

    Returns:
        None: Assertions verify text preservation, adaptive line widths, and centered clouds on first and continuation pages.

    Raises:
        AssertionError: Body text is lost, overlaps the profile, or leaves unnecessary gaps at its lower edge.
    """
    settings = GitHubContributions(enabled=True, as_of="2026-10-07")
    start, end = calendar_window(settings)
    calendar = ContributionCalendar(
        "layout-check",
        start.isoformat(),
        end.isoformat(),
        [ContributionDay((start + timedelta(days=offset)).isoformat(), 0, 0) for offset in range((end - start).days + 1)],
    )
    words = [f"word{index:03d}" for index in range(650)]
    sentence = "Build practical tools and reliable platforms for engineering teams, improving delivery speed and operational consistency."
    transitions: list[int] = []
    skills = Section("skills", "Skills", [Entry("Python", skills=[Skill("Python", 2), Skill("Rust", 1)])])

    # Both previews use one uninterrupted paragraph, so moving it wholesale below the profile cannot pass.
    with tempfile.TemporaryDirectory(prefix="profile-layout-", dir=Path.cwd()) as directory:
        root = Path(directory)
        Image.new("RGB", (200, 200), "#dddddd").save(root / "portrait.png")
        Image.new("RGB", (600, 150), "#eeeeee").save(root / "cover.png")

        for expanded in (False, True):
            name = "expanded" if expanded else "compact"
            headline = "Engineering reliable platforms and developer infrastructure"
            profile = Profile(
                "layout-check",
                "Layout Check",
                intro=[headline, "Boston, MA"],
                headline=headline,
                images=[
                    Media("https://example.org/portrait.png", "Profile photo", path="portrait.png"),
                    Media("https://example.org/cover.png", "Cover photo", path="cover.png"),
                ]
                if expanded
                else [],
                sections=[Section("about", "About", [Entry(paragraphs=[sentence, " ".join(words)])]), skills],
            )
            config = Config(
                LinkedIn(profile.username),
                github=GitHub("layout-check", evolve(settings, enabled=expanded)),
                style=Style(
                    profile_column_side="right",
                    profile_column_wrap=True,
                    show_headline=expanded,
                    show_header_photo=expanded,
                    show_table_of_contents=expanded,
                ),
                output=Output(tex=f"{name}/resume.tex", pdf=f"{name}/resume.pdf"),
            )
            source = render_profile(profile, config, root, contributions=calendar if expanded else None)
            pdf = compile_pdf(source, config, root)
            rows = _rows(pdf)
            cloud_page = _assert_cloud_centered(pdf, next((source.parent / "assets").glob("skills-*.png")))
            assert cloud_page > 1, f"{name}: fixture did not exercise a continuation-page cloud"
            text = " ".join(row[1] for row in rows)
            assert re.findall(r"word\d{3}", text) == words, f"{name}: lost, repeated, or reordered body text"
            assert not re.search(r"\d+\.\d+pt", text), f"{name}: layout dimensions leaked into visible text"
            first_sentence_line = next(text for _, text, _, _ in rows if text.startswith("Build practical"))
            assert len(first_sentence_line) > len(sentence) / 2, f"{name}: short paragraph wrapped prematurely"
            body = [(re.findall(r"word\d{3}", text), y) for page, text, _, y in rows if page == 1 and "word" in text]
            widest = max(len(line) for line, _ in body)
            transition = next(index for index, (line, _) in enumerate(body) if len(line) >= widest - 1)
            assert transition > 0, f"{name}: paragraph started across the profile column"
            assert widest >= len(body[0][0]) * 1.25, f"{name}: text never widened below the profile"

            # Header baselines sit in the right column; body rows always start on the left even after widening.
            header_bottom = min(y for page, text, x, y in rows if page == 1 and x > 420 and y > 60 and "word" not in text)
            assert 0 < header_bottom - body[transition][1] < 36, f"{name}: wrapping ended too early or reserved extra lines"
            assert all(0 < upper[1] - lower[1] < 15 for upper, lower in pairwise(body)), f"{name}: gap inside paragraph"
            transitions.append(transition)
            print(f"{name}: continuous paragraph widens after {transition} lines; cloud centered on page {cloud_page}")

        assert transitions[1] > transitions[0], "Enabling profile content did not increase its wrapping exclusion"

        # Fixed columns reserve the profile's side for the whole first page, even when the profile is very short.
        paragraphs = [f"Paragraph {index:03d}. {sentence}" for index in range(50)]
        profile = Profile("layout-check", "Layout Check", sections=[Section("about", "About", [Entry(paragraphs=paragraphs)])])
        config = Config(
            LinkedIn(profile.username),
            style=Style(profile_column_side="right", show_table_of_contents=False),
            output=Output(tex="fixed/resume.tex", pdf="fixed/resume.pdf"),
        )
        rows = _rows(compile_pdf(render_profile(profile, config, root), config, root))
        text = " ".join(row[1] for row in rows)
        assert re.findall(r"Paragraph \d{3}", text) == [f"Paragraph {index:03d}" for index in range(50)]
        first_lines = [(page, text, y) for page, text, _, y in rows if text.startswith("Paragraph ")]
        narrow_lengths = [len(text) for page, text, _ in first_lines if page == 1]
        wide_lengths = [len(text) for page, text, _ in first_lines if page > 1]
        assert len(narrow_lengths) > 5 and min(y for page, _, y in first_lines if page == 1) < 300
        assert len(set(narrow_lengths)) == 1, "Fixed first-page paragraphs widened below the profile"
        assert min(wide_lengths) > max(narrow_lengths), "Continuation pages did not resume full-width body text"
        print("fixed: first-page paragraphs retain their column width; continuation pages use full width")

        # A short profile must not force an otherwise fitting Projects section onto a new page.
        profile = Profile(
            "layout-check",
            "Layout Check",
            sections=[
                Section(
                    "projects",
                    "Projects",
                    [Entry("Project proof", ["Complete project description"], [Link("Source", "https://github.com/example/project")])],
                ),
                skills,
            ],
        )
        config = Config(
            LinkedIn(profile.username), style=Style(profile_column_side="right", profile_column_wrap=True, show_table_of_contents=False)
        )
        source = render_profile(profile, config, root)
        pdf = compile_pdf(source, config, root)
        rows = _rows(pdf)
        assert any(page == 1 and "Project proof" in text for page, text, _, _ in rows), "Short profile stranded Projects on page two"
        assert _assert_cloud_centered(pdf, next((source.parent / "assets").glob("skills-*.png"))) == 1, "Cloud fixture left page one"
        print("projects: first-page space reused below the profile; cloud centered on page one")

        # An oversized optional Contact section must remain breakable rather than clipping a measured identity box.
        details = [f"Contact detail {index:03d}" for index in range(80)]
        profile = Profile(
            "layout-check",
            "Layout Check",
            sections=[
                Section("contact", "Contact", [Entry(paragraphs=details)]),
                Section("about", "About", [Entry(paragraphs=[sentence])]),
            ],
        )
        config = evolve(config, section_order=["contact", "about"])
        rows = _rows(compile_pdf(render_profile(profile, config, root), config, root))
        text = " ".join(row[1] for row in rows)
        assert re.findall(r"Contact detail \d{3}", text) == details, "Tall profile lost or duplicated contact details"
        assert sentence in text, "Body did not resume at full width after the tall profile"
        assert any(page > 1 and "Build practical" in text for page, text, _, _ in rows), "Tall profile did not continue onto another page"
        print("oversized: complete profile preserved across column and page boundaries")


if __name__ == "__main__":
    main()
