"""
Define independent dispatch authorization and per-figure appendix visibility controls.
"""

from __future__ import annotations

from attrs import field, frozen

FIGURES = {
    "knowledge-usage": "knowledge",
    "knowledge-map": "knowledge",
    "decision-influences": "life",
    "knowledge-hierarchy": "knowledge",
    "toolbox-use": "repertoire",
    "problem-repertoire": "repertoire",
    "checkpoint-transitions": "checkpoints",
    "checkpoint-comparisons": "checkpoints",
}
FIGURE_LABELS = {
    "knowledge-usage": "Applied skills",
    "knowledge-map": "Connected skills",
    "decision-influences": "Engineering judgment",
    "knowledge-hierarchy": "Knowledge breadth",
    "toolbox-use": "Engineering tools",
    "problem-repertoire": "Problem solving",
    "checkpoint-transitions": "Professional growth",
    "checkpoint-comparisons": "Experience progression",
}
BUNDLE_PATH = "data/awareness.json"
MAX_BUNDLE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_BYTES = 2 * 1024 * 1024


@frozen
class Awareness:
    """
    Authorize external rebuild requests separately from document content selection.

    Attributes:
        enabled (bool): Accept authenticated awareness dispatches; disabled by default.
        allowed_actors (tuple[str, ...]): Exact GitHub user or App bot logins allowed to request a rebuild.
    """

    enabled: bool = False
    allowed_actors: tuple[str, ...] = ()


@frozen
class FigureSelector:
    """
    Match a figure by any supplied fields, with all fields in one selector required to match.

    Attributes:
        id (str | None): Exact figure identifier; None imposes no restriction.
        group (str | None): Exact category; None imposes no restriction.
    """

    id: str | None = None
    group: str | None = None


@frozen
class AwarenessAppendix:
    """
    Choose enabled figures in mapping order, then apply includes and exclusions.

    Attributes:
        figures (dict[str, bool]): Individual visibility switches; missing keys remain disabled.
        include (tuple[FigureSelector, ...]): Optional allowlist narrowing explicitly enabled figures.
        exclude (tuple[FigureSelector, ...]): Denylist taking precedence over inclusion and visibility.
    """

    figures: dict[str, bool] = field(factory=dict)
    include: tuple[FigureSelector, ...] = ()
    exclude: tuple[FigureSelector, ...] = ()


@frozen
class Appendices:
    """
    Group optional evidence appendices independently of LinkedIn profile sections.

    Attributes:
        awareness (AwarenessAppendix): Per-figure selection; no figures appear by default.
    """

    awareness: AwarenessAppendix = field(factory=AwarenessAppendix)


def selected_figures(settings: AwarenessAppendix) -> tuple[str, ...]:
    """
    Resolve independent enable switches with OR selectors and exclusion precedence.

    Args:
        settings (AwarenessAppendix): Validated display configuration.

    Returns:
        tuple[str, ...]: Selected catalog IDs in configured insertion order.
    """

    def matches(key: str, selector: FigureSelector) -> bool:
        """
        Require every supplied selector field to match a catalog entry.

        Args:
            key (str): Known figure ID.
            selector (FigureSelector): Nonempty field filter.

        Returns:
            bool: Whether ID and category constraints both match.
        """
        return (selector.id is None or selector.id == key) and (selector.group is None or selector.group == FIGURES[key])

    return tuple(
        key
        for key, enabled in settings.figures.items()
        if enabled
        and (not settings.include or any(matches(key, item) for item in settings.include))
        and not any(matches(key, item) for item in settings.exclude)
    )
