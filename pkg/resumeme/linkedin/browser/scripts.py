"""
Load JavaScript used by Selenium from standalone package resources.
"""

from __future__ import annotations

from importlib.resources import files

__all__ = [
    "CLICK_ELEMENT",
    "EXPOSE_FILE_INPUT",
    "PROFILE_CONTENT_STATE",
    "READ_ABOUT_EDITOR",
    "RESTORE_FILE_INPUT",
    "SCROLL_ELEMENT_INTO_VIEW",
    "SCROLL_PROFILE_CONTENT",
]

_SCRIPTS = files("resumeme.linkedin").joinpath("scripts")

# Keep page-execution code as independently linted assets and load it once per process.
CLICK_ELEMENT = _SCRIPTS.joinpath("click_element.js").read_text(encoding="utf-8")
EXPOSE_FILE_INPUT = _SCRIPTS.joinpath("expose_file_input.js").read_text(encoding="utf-8")
PROFILE_CONTENT_STATE = _SCRIPTS.joinpath("profile_content_state.js").read_text(encoding="utf-8")
READ_ABOUT_EDITOR = _SCRIPTS.joinpath("read_about_editor.js").read_text(encoding="utf-8")
RESTORE_FILE_INPUT = _SCRIPTS.joinpath("restore_file_input.js").read_text(encoding="utf-8")
SCROLL_ELEMENT_INTO_VIEW = _SCRIPTS.joinpath("scroll_element_into_view.js").read_text(encoding="utf-8")
SCROLL_PROFILE_CONTENT = _SCRIPTS.joinpath("scroll_profile_content.js").read_text(encoding="utf-8")
