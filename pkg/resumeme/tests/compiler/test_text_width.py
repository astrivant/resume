"""
Validate body-width configuration independently of profile placement and theme selection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml
from jsonschema import ValidationError

from resumeme.compiler.passes.themes import resolve_style
from resumeme.config import CompanyTarget, company_config, load_config
from resumeme.exceptions import ConfigurationError

if TYPE_CHECKING:
    from pathlib import Path


def test_body_width_defaults_and_theme_preserve_column_settings(tmp_path: Path) -> None:
    """
    Keep the later-page and first-page body widths independent under theme selection.

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


@pytest.mark.parametrize("grouped", [False, True])
def test_legacy_width_names_normalize_before_themes_and_company_merges(tmp_path: Path, grouped: bool) -> None:
    """
    Preserve old base, theme, and per-company values through the input migration.

    Args:
        tmp_path (Path): Isolated configuration directory.
        grouped (bool): Whether the style uses the grouped public path.

    Returns:
        None: Aliases resolve to canonical fields before inherited values are merged.
    """
    style = {"text_wrap_width": 0.88, "profile_column_text_wrap_width": 1.0}
    raw = {"linkedin": {"username": "example-person"}, **({"document": {"style": style}} if grouped else {"style": style})}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw))
    config = load_config(path)
    assert config.style.first_page_body_width == 1.0
    assert config.style.later_page_body_width == 0.88

    # The same spelling may replace a canonical inherited value in a separate override mapping.
    override = {
        "text_wrap_width": 0.65,
        "theme": "narrow",
        "themes": {"narrow": {"profile_column_text_wrap_width": 0.8}},
    }
    target = CompanyTarget("example-company", "https://www.linkedin.com/jobs/view/123/", overrides={"document": {"style": override}})
    resolved = resolve_style(company_config(config, target, root=tmp_path).style)
    assert (resolved.first_page_body_width, resolved.later_page_body_width) == (0.8, 0.65)
    assert (config.style.first_page_body_width, config.style.later_page_body_width) == (1.0, 0.88)


@pytest.mark.parametrize(
    ("legacy", "canonical"),
    [("text_wrap_width", "later_page_body_width"), ("profile_column_text_wrap_width", "first_page_body_width")],
)
@pytest.mark.parametrize("theme", [False, True])
def test_width_aliases_reject_ambiguous_values(tmp_path: Path, legacy: str, canonical: str, theme: bool) -> None:
    """
    Reject two names for the same setting even when their supplied values are equal.

    Args:
        tmp_path (Path): Isolated configuration directory.
        legacy (str): Former field name.
        canonical (str): Current field name for the same setting.
        theme (bool): Whether the duplicate belongs to a named theme.

    Returns:
        None: Validation names the canonical replacement without selecting a winner.
    """
    values = {legacy: 1.0, canonical: 1.0}
    style = {"themes": {"custom": values}} if theme else values
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"profile": {"linkedin": {"username": "example-person"}}, "document": {"style": style}}))

    with pytest.raises(ConfigurationError, match=canonical):
        load_config(path)
