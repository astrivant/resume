"""
Escape profile text, emoji, and URLs for LaTeX template expressions.
"""

from __future__ import annotations

import re

__all__ = ["latex_escape", "latex_url"]

_ESCAPES = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}
_EMOJI = re.compile(
    "[\U0001f1e6-\U0001f1ff]{2}|[#*0-9]\ufe0f?\u20e3|"
    "[\U0001f300-\U0001faff\u2600-\u27bf](?:\ufe0f|[\U0001f3fb-\U0001f3ff])?"
    "(?:\u200d[\U0001f300-\U0001faff\u2600-\u27bf](?:\ufe0f|[\U0001f3fb-\U0001f3ff])?)*"
)


def latex_escape(value: str) -> str:
    """
    Escape each input character once so profile text cannot become TeX commands.

    Args:
        value (str): Untrusted display text.

    Returns:
        str: Text suitable for a LaTeX argument.
    """

    # Split emoji sequences from ordinary text so generated TeX commands are never escaped a second time.
    parts: list[str] = []
    offset = 0

    for match in _EMOJI.finditer(value):
        parts.append("".join(_ESCAPES.get(character, character) for character in value[offset : match.start()]))
        emoji = match.group()

        # Twemoji filenames omit presentation selectors on simple emoji but retain them inside joined sequences.
        if "\u200d" not in emoji:
            emoji = emoji.replace("\ufe0f", "")

        code = "-".join(f"{ord(character):x}" for character in emoji)
        parts.append(r"\texttwemoji{" + code + "}")
        offset = match.end()

    parts.append("".join(_ESCAPES.get(character, character) for character in value[offset:]))
    return "".join(parts)


def latex_url(value: str) -> str:
    """
    Quote special URL characters for hyperref while retaining the destination.

    Args:
        value (str): Validated HTTP URL.

    Returns:
        str: Escaped hyperlink argument.
    """

    # URL validation already rejected structural TeX characters; escape remaining hyperref-sensitive characters without rewriting the URL.
    return "".join({"%": r"\%", "#": r"\#", "&": r"\&", "_": r"\_"}.get(character, character) for character in value)
