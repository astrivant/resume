"""
Recognize employment location metadata and construct offline Google Maps links.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlencode

from resumeme.compiler.asts.dates import employment_period
from resumeme.compiler.asts.profile import Link
from resumeme.compiler.constants.locations import CONNECTORS as _CONNECTORS
from resumeme.compiler.constants.locations import DURATION as _DURATION
from resumeme.compiler.constants.locations import HEADINGS as _HEADINGS
from resumeme.compiler.constants.locations import PLACE as _PLACE
from resumeme.compiler.constants.locations import WORK_MODES as _WORK_MODES

if TYPE_CHECKING:
    from resumeme.compiler.asts.profile import Entry

__all__ = ["job_locations"]


def _location_link(line: str) -> Link | None:
    """
    Identify a place in a metadata slot without interpreting work arrangements as geography.

    Args:
        line (str): Line immediately following employment dates or a grouped company's duration.

    Returns:
        Link | None: Encoded map destination and original place label, or None for non-location text.
    """
    place, separator, mode = line.partition("·")
    place = place.rstrip()
    words = place.split()

    # Metadata positions may contain a heading or description when a job has no recorded location.
    if (
        not words
        or len(words) > 12
        or len(place) > 160
        or place.casefold() in _WORK_MODES | _HEADINGS
        or employment_period(place) is not None
        or not _PLACE.fullmatch(place)
        or place.endswith(".")
        or (separator and mode.strip().casefold() not in _WORK_MODES)
    ):
        return None

    # Place names are normally capitalized; allow geographic connectors and scripts without letter case.
    # This deliberately leaves sentence-like prose unchanged when the optional location row is absent.
    if not all(word in _CONNECTORS or not word[0].islower() for word in words):
        return None

    destination = "https://www.google.com/maps/search/?" + urlencode({"api": "1", "query": place})
    return Link(place, destination)


def job_locations(entry: Entry) -> dict[str, Link]:
    """
    Associate location rows with map links for standalone and grouped employment.

    Args:
        entry (Entry): Visible job or company group after job exclusions have been applied.

    Returns:
        dict[str, Link]: Full metadata lines mapped to their geographic label and Google Maps destination.
    """
    lines = [line.strip() for paragraph in entry.paragraphs for line in paragraph.splitlines()]
    candidates = {index + 1 for index, line in enumerate(lines) if employment_period(line)}

    # Older company groups store a shared location after the total tenure, before any individual role title.
    if lines and _DURATION.fullmatch(lines[0].rsplit("·", 1)[-1].strip()):
        candidates.add(1)

    result: dict[str, Link] = {}

    for index in sorted(candidates):
        if index < len(lines) and (link := _location_link(lines[index])) is not None:
            result[lines[index]] = link

    # Custom templates may consume explicit roles whose lines were not retained in a legacy flattened group.
    for position in entry.positions:
        result.update(job_locations(position))

    return result
