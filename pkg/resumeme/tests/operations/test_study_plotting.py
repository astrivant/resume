"""
Keep the question each study answers visible in its generator and published figure.
"""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

import pytest
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from scripts.studies.plotting import question_header

STUDIES = Path(__file__).parents[4] / "studies"


@pytest.mark.parametrize("size", [(6.4, 4.8), (15, 8), (12, 8), (14, 10)])
def test_question_header_has_separate_visible_bounds(size: tuple[float, float]) -> None:
    """
    Verify physical separation of wrapped titles, questions, and panels after export layout.

    Args:
        size (tuple[float, float]): Small and production study figure dimensions in inches.

    Returns:
        None: The complete header stays inside the image and above panel labels.
    """
    figure = Figure(figsize=size)
    axis = figure.subplots()
    axis.set_title("Observed measurement")
    question_header(
        figure,
        "Capacity adaptation: paired seeds with cooldown and startup overhead",
        "Which policies reach balanced shard runtimes sooner under noise and changing workloads?",
    )
    FigureCanvasAgg(figure)
    figure.draw_without_rendering()
    title, question = figure.texts
    title_bounds, question_bounds, panel_bounds = [artist.get_window_extent() for artist in (title, question, axis.title)]
    assert question.get_gid() == "plot-question"
    assert title_bounds.y1 < figure.bbox.y1
    assert title_bounds.y0 > question_bounds.y1
    assert question_bounds.y0 > panel_bounds.y1
    assert question_bounds.x0 > figure.bbox.x0 and question_bounds.x1 < figure.bbox.x1


@pytest.mark.parametrize("path", sorted(STUDIES.rglob("*.svg")), ids=lambda path: str(path.relative_to(STUDIES)))
def test_published_study_has_a_reader_question(path: Path) -> None:
    """
    Catch new or regenerated study figures that omit the visible question subtitle.

    Args:
        path (Path): Published study SVG, including figures in nested directories.

    Returns:
        None: Exactly one nonempty question is retained in the exported figure.
    """
    # Matplotlib can export text as font paths, retaining the original words as XML comments.
    parser = ElementTree.XMLParser(target=ElementTree.TreeBuilder(insert_comments=True))
    root = ElementTree.fromstring(path.read_text(encoding="utf-8"), parser=parser)
    questions = [element for element in root.iter() if element.get("id") == "plot-question"]
    assert len(questions) == 1, f"{path}: expected one question subtitle"
    text = " ".join("".join(questions[0].itertext()).split())
    assert len(text) > 1 and text.endswith("?"), f"{path}: subtitle must state the plot's question"
