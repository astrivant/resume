"""
Type the WordCloud 1.9 public API used by resume; upstream does not ship type hints.
"""

from collections.abc import Mapping
from typing import Self

from PIL.Image import Image

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
        max_words: int,
        min_font_size: int,
        max_font_size: int,
        prefer_horizontal: float,
        relative_scaling: float,
        random_state: int,
    ) -> None: ...
    def generate_from_frequencies(self, frequencies: Mapping[str, float]) -> Self: ...
    def to_image(self) -> Image: ...
