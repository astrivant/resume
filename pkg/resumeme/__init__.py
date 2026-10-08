"""
Capture and render a portable, illustrated LinkedIn profile.
"""

from __future__ import annotations

import logging

__all__: list[str] = []

# Library callers own logging configuration; importing resumeme must not install a console handler.
logging.getLogger(__name__).addHandler(logging.NullHandler())
