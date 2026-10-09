"""
Give study figures a concise reader question below the title, with space reserved for both.
"""

from __future__ import annotations

from textwrap import fill
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from matplotlib.figure import Figure

__all__ = ["question_header"]


def question_header(figure: Figure, title: str, question: str) -> None:
    """
    Reserve a physical header above constrained-layout panels and their legends.

    Args:
        figure (Figure): Study figure whose panels use constrained layout.
        title (str): Descriptive figure title.
        question (str): Concise, explicit question answered by the plotted measurements.

    Returns:
        None: The figure contains a title and a separately identifiable question subtitle.

    Raises:
        ValueError: The subtitle is blank or does not state a question.
    """
    if not question.strip().endswith("?") or len(question.strip()) < 2:
        raise ValueError("A study subtitle must state the question its measurements answer")

    # Reserve space in inches so the subtitle stays readable across differently sized study figures.
    width, height = figure.get_size_inches()
    title = fill(title, width=max(30, int(width * 8)), break_long_words=False, break_on_hyphens=False)
    question = fill(question, width=max(35, int(width * 12)), break_long_words=False, break_on_hyphens=False)
    title_height = 0.25 * len(title.splitlines())
    question_top = 0.18 + title_height
    header_height = question_top + 0.2 * len(question.splitlines()) + 0.18
    heading = figure.suptitle(title, y=1 - 0.10 / height, va="top", fontsize=16)
    heading.set_in_layout(False)
    subtitle = figure.text(0.5, 1 - question_top / height, question, ha="center", va="top", fontsize=10, color="#475569")
    subtitle.set_gid("plot-question")
    subtitle.set_in_layout(False)

    # Constrained layout must retain this reserved header when savefig recalculates panel positions.
    figure.set_layout_engine("constrained", rect=(0, 0, 1, 1 - header_height / height))
