"""
Match optional selector fields while leaving metadata extraction and normalization to each pass.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Collection

__all__ = ["matches_fields"]


def matches_fields(*fields: tuple[str | None, Collection[str], Callable[[str], str]]) -> bool:
    """
    Require every supplied filter field to match one of its captured values.

    Args:
        *fields (tuple[str | None, Collection[str], Callable[[str], str]]): Requested value, captured values, and normalizer per field.

    Returns:
        bool: Whether all supplied fields match; omitted fields impose no restriction.
    """

    # Selectors combine fields with AND; each pass chooses the metadata values that can satisfy a field.
    # Configuration validation requires at least one field, keeping empty mappings from becoming catch-all filters.
    return all(
        requested is None or any(normalize(requested) == normalize(value) for value in values) for requested, values, normalize in fields
    )
