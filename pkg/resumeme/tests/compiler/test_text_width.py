"""
Validate body-width configuration independently of profile placement and theme selection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml
from jsonschema import ValidationError

from resumeme.compiler.passes.themes import resolve_style
from resumeme.config import load_config

if TYPE_CHECKING:
    from pathlib import Path


def test_body_width_defaults_and_theme_preserve_column_settings(tmp_path: Path) -> None:
    """
    Keep the global and first-page column width controls independent under theme selection.

    Args:
        tmp_path (Path): Isolated configuration directory.

    Returns:
        None: Theme resolution changes only requested fields and leaves the base style untouched.
    """
    path = tmp_path / "resumeme.config.yaml"
    path.write_text(
        "linkedin: {username: example-person}\n"
        "style:\n  profile_column_side: right\n  profile_column_wrap: true\n"
        "  theme: full\n  themes: {full: {later_page_body_width: 1, first_page_body_width: 0.95}}\n"
    )
    base = load_config(path).style
    effective = resolve_style(base)
    assert base.later_page_body_width == 0.9
    assert effective.later_page_body_width == 1
    assert base.first_page_body_width == 1
    assert effective.first_page_body_width == 0.95
    assert effective.profile_column_side == base.profile_column_side == "right"
    assert effective.profile_column_wrap is base.profile_column_wrap is True
    assert base.later_page_body_width == 0.9


@pytest.mark.parametrize(
    ("field", "value"),
    [(field, value) for field in ("later_page_body_width", "first_page_body_width") for value in (0, -0.1, 1.01, 90, True, "90%", None)],
)
@pytest.mark.parametrize("theme", [False, True])
def test_body_width_rejects_invalid_base_and_theme_values(tmp_path: Path, field: str, value: object, theme: bool) -> None:
    """
    Reject percentages, empty widths, and invalid types before rendering.

    Args:
        tmp_path (Path): Isolated configuration directory.
        field (str): Width setting under validation.
        value (object): Invalid width ratio.
        theme (bool): Whether the input is supplied as an inline theme override.

    Returns:
        None: Both configuration locations enforce the same numeric interval.
    """
    override = {field: value}
    style = {"themes": {"custom": override}} if theme else override
    path = tmp_path / "resumeme.config.yaml"
    path.write_text(yaml.safe_dump({"linkedin": {"username": "example-person"}, "style": style}))

    with pytest.raises(ValidationError):
        load_config(path)
