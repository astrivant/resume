"""
Type the WordCloud 1.9 public API used by resume; upstream does not ship type hints.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, Self

from PIL.Image import Image

class _ColorFunction(Protocol):
    def __call__(self, *args: object, **kwargs: object) -> str: ...

class WordCloud:
    layout_: list[object]
    def __init__(
        self,
        *,
        font_path: str,
        width: int,
        height: int,
        background_color: str,
        colormap: str,
        color_func: _ColorFunction,
        max_words: int,
        min_font_size: int,
        max_font_size: int,
        prefer_horizontal: float,
        relative_scaling: float,
        random_state: int,
    ) -> None: ...
    def generate_from_frequencies(self, frequencies: Mapping[str, float]) -> Self: ...
    def to_image(self) -> Image: ...
