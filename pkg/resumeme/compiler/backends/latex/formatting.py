"""
Format generated LaTeX source for review without changing its commands.
"""

from __future__ import annotations

__all__ = ["format_tex_source"]


def format_tex_source(source: str) -> str:
    """
    Keep one blank line between source blocks and preserve final-newline policy.

    LaTeX treats one or more empty lines as the same paragraph boundary. Jinja can
    emit long runs of them inside loops, so this pass reduces each run while
    preserving every nonblank line and all generated TeX tokens.

    Args:
        source (str): LaTeX emitted by the configured Jinja template.

    Returns:
        str: Readable LaTeX source with normalized blank-line spacing.
    """

    # Retain the caller's template-level final-newline choice, which custom templates can observe.
    has_final_newline = source.endswith(("\n", "\r"))

    # Preserve command lines exactly; only normalize lines containing whitespace.
    formatted: list[str] = []
    blank_pending = False

    for line in source.splitlines():
        if line.strip():
            formatted.append(line)
            blank_pending = False
            continue

        # Retain a single separator after content, while dropping leading and repeated blank lines.
        if formatted and not blank_pending:
            formatted.append("")
            blank_pending = True

    # Keep packaged source editor-friendly without changing custom template boundaries.
    result = "\n".join(formatted)
    return result.rstrip("\n") + "\n" if has_final_newline and result else result
