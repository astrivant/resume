"""
Render a stable SVG badge from the combined pytest coverage report without external services.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree

report = ElementTree.parse(".cache/coverage/coverage.xml").getroot()
covered = int(report.attrib["lines-covered"])
total = int(report.attrib["lines-valid"])

# Missing or inconsistent results must fail publication instead of presenting an invented coverage percentage.
if total <= 0 or not 0 <= covered <= total:
    raise ValueError("Coverage badge requires a nonempty report with valid covered and total line counts.")

percent = Decimal(covered * 100) / Decimal(total)
label = f"{percent:.1f}".removesuffix(".0") + "%"
color = "#4c1" if percent >= 90 else "#97ca00" if percent >= 75 else "#dfb317" if percent >= 60 else "#e05d44"

# Keep the output deterministic so unchanged percentages produce no publication commit.
badge = f'''<svg xmlns="http://www.w3.org/2000/svg" width="124" height="20" role="img" aria-label="coverage: {label}">
  <title>Python coverage: {label}</title>
  <linearGradient id="shine" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="rounded"><rect width="124" height="20" rx="3" fill="#fff"/></clipPath>
  <g clip-path="url(#rounded)">
    <path fill="#555" d="M0 0h65v20H0z"/>
    <path fill="{color}" d="M65 0h59v20H65z"/>
    <path fill="url(#shine)" d="M0 0h124v20H0z"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">
    <text x="32.5" y="15" fill="#010101" fill-opacity=".3">coverage</text>
    <text x="32.5" y="14">coverage</text>
    <text x="94.5" y="15" fill="#010101" fill-opacity=".3">{label}</text>
    <text x="94.5" y="14">{label}</text>
  </g>
</svg>
'''
destination = Path(".cache/coverage-badge/coverage.svg")
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(badge, encoding="utf-8")
