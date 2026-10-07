"""
Locate packaged compiler resources and define deterministic target-generation settings.
"""

from __future__ import annotations

__all__ = [
    "AST_PACKAGE",
    "LATEX_PACKAGE",
    "CONFIG_SCHEMA",
    "PROFILE_SCHEMA",
    "TEMPLATE",
    "TOOLCHAIN",
    "FONT_ARCHIVE",
    "CLOUD_FONT",
    "SECTION_ORDER",
    "SOURCE_DATE_EPOCH",
    "COMPILER_TIMEOUT_SECONDS",
    "BLOCK_START",
    "BLOCK_END",
    "VARIABLE_START",
    "VARIABLE_END",
    "COMMENT_START",
    "COMMENT_END",
]

AST_PACKAGE = "resumeme.compiler.asts"
LATEX_PACKAGE = "resumeme.compiler.backends.latex"
CONFIG_SCHEMA = "resources/config.schema.json"
PROFILE_SCHEMA = "resources/profile.schema.json"
TEMPLATE = "resources/resume.tex.j2"
TOOLCHAIN = "resources/toolchain.json"
FONT_ARCHIVE = "resources/fonts/ebgaramond-texmf.zip"
CLOUD_FONT = "resources/fonts/EBGaramond-Regular.otf"

# Keep destination numbering independent of source title spelling and rendered language.
SECTION_ORDER = {"contact": 0, "about": 1}
SOURCE_DATE_EPOCH = "946684800"
COMPILER_TIMEOUT_SECONDS = 120

# These delimiters leave ordinary TeX braces untouched during template expansion.
BLOCK_START, BLOCK_END = "((*", "*))"
VARIABLE_START, VARIABLE_END = "(((", ")))"
COMMENT_START, COMMENT_END = "((#", "#))"
