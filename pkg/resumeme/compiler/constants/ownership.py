"""
Define the managed ownership-field grammar shared by display cleanup.
"""

from __future__ import annotations

import re

__all__ = ["OWNERSHIP_FIELD"]

# These labels are the publisher's protocol, independent of a person's name, fingerprint, or release host.
OWNERSHIP_FIELD = re.compile(r"^\s*(resume\s+signature|releases)\s*:", re.IGNORECASE)
