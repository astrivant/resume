"""
Apply inline theme overrides before filtering media, rendering text, or generating illustrations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from attrs import evolve

from resumeme.exceptions import ConfigurationError

if TYPE_CHECKING:
    from resumeme.config import Style

__all__ = ["resolve_style"]


def resolve_style(style: Style) -> Style:
    """
    Overlay the selected inline theme on base style values without modifying the source configuration.

    Args:
        style (Style): Base presentation values, optional selector, and inline theme definitions.

    Returns:
        Style: Effective presentation values; omitted theme fields retain their base values.

    Raises:
        ConfigurationError: The selected name is absent from style.themes, including configs constructed directly in Python.
    """

    if style.theme is None:
        return style

    if style.theme not in style.themes:
        raise ConfigurationError(f"Unknown style.theme {style.theme!r}; define it under style.themes or use null.")

    # Apply overrides by key presence so False remains meaningful; theme/themes themselves cannot be overridden.
    return evolve(style, **style.themes[style.theme])
