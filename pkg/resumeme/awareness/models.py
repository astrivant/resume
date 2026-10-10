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

# Keep explanations tied to the public figure contract, independent of an owner's titles or private source journals.
FIGURE_DESCRIPTIONS = {
    "knowledge-usage": (
        "These counts show which skills and concepts have been applied in recorded tasks. "
        "The left panel separates levels of understanding; the right groups applications under their skills, including related lessons. "
        "The verified portion identifies observations recorded with supporting checks, showing where practice has been documented."
    ),
    "knowledge-map": (
        "Each bubble groups an engineering discipline and its skills; the connections show how ideas are organized and reused across "
        "areas of work. Larger, more central bubbles reflect greater recent recorded use. "
        "The shaded distribution, ellipses, and center mark summarize that working emphasis; fading indicates peripheral focus, "
        "not forgotten skills. Together, they show how different parts of my engineering practice support one another."
    ),
    "decision-influences": (
        "The bars show which skills and lessons inform my current accepted engineering decisions. "
        "Each count represents a decision that explicitly references that concept; revised decisions replace earlier versions, "
        "and retired decisions are excluded. This makes recurring influences on my judgment visible, grounded in recorded choices "
        "rather than a self-assessed skill rating."
    ),
    "knowledge-hierarchy": (
        "This view organizes engineering knowledge into disciplines, skills, lessons, and supporting insights. "
        "The nesting connects broad areas of practice to the more specific guidance used within them. "
        "It describes the breadth and structure of a maintained knowledge collection, rather than how often each skill is used."
    ),
    "toolbox-use": (
        "The bars rank tools by the distinct recorded tasks in which they were used. "
        "Only the latest observation of each task contributes, so revising a record does not inflate its count. "
        "This shows the practical toolkit behind my work and which tools recur across documented tasks."
    ),
    "problem-repertoire": (
        "This diagram connects specific kinds of engineering problems to their broader categories. "
        "Task counts show where work has been recorded within that structure, linking concrete assignments to recurring problem-solving "
        "themes. The view describes the range of problems encountered and how they relate to one another."
    ),
    "checkpoint-transitions": (
        "Each column compares consecutive project visits, showing changes in the lessons and skill applications recorded between them. "
        "Cell annotations distinguish additions, removals, and revisions; stronger shading indicates more changes. "
        "This traces how documented practice evolves from one project to the next, including corrections to earlier records."
    ),
    "checkpoint-comparisons": (
        "This view compares the latest recorded state with earlier project visits. "
        "Each column shows changes in lessons and skill applications since that earlier point, with additions, removals, and revisions "
        "kept distinct. It places current engineering practice in context and shows which parts of the record have evolved over time."
    ),
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
