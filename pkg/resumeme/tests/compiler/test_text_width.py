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
    Default to ninety percent while letting a theme independently select full-width prose.

    Args:
        tmp_path (Path): Isolated configuration directory.

    Returns:
        None: Theme resolution changes only requested fields and leaves the base style untouched.
    """
    path = tmp_path / "resumeme.config.yaml"
    path.write_text(
        "linkedin: {username: example-person}\n"
        "style:\n  profile_column_side: right\n  profile_column_wrap: true\n"
        "  theme: full\n  themes: {full: {text_wrap_width: 1}}\n"
    )
    base = load_config(path).style
    effective = resolve_style(base)
    assert base.text_wrap_width == 0.9
    assert effective.text_wrap_width == 1
    assert effective.profile_column_side == base.profile_column_side == "right"
    assert effective.profile_column_wrap is base.profile_column_wrap is True
    assert base.text_wrap_width == 0.9


@pytest.mark.parametrize("value", [0, -0.1, 1.01, 90, True, "90%", None])
@pytest.mark.parametrize("theme", [False, True])
def test_body_width_rejects_invalid_base_and_theme_values(tmp_path: Path, value: object, theme: bool) -> None:
    """
    Reject percentages, empty widths, and invalid types before rendering.

    Args:
        tmp_path (Path): Isolated configuration directory.
        value (object): Invalid width ratio.
        theme (bool): Whether the input is supplied as an inline theme override.

    Returns:
        None: Both configuration locations enforce the same numeric interval.
    """
    override = {"text_wrap_width": value}
    style = {"themes": {"custom": override}} if theme else override
    path = tmp_path / "resumeme.config.yaml"
    path.write_text(yaml.safe_dump({"linkedin": {"username": "example-person"}, "style": style}))

    with pytest.raises(ValidationError):
        load_config(path)
