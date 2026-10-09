"""
Bind relative date settings to an explicit compilation input without consulting the clock.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from attrs import evolve

if TYPE_CHECKING:
    from datetime import date

    from resumeme.config import Config

__all__ = ["resolve_dates"]


def resolve_dates(config: Config, *, today: date) -> Config:
    """
    Pin missing date endpoints once while preserving user-specified endpoints.

    Args:
        config (Config): Validated settings whose relative windows need a reference date.
        today (date): Explicit UTC reference selected by the orchestration boundary.

    Returns:
        Config: Independent settings used consistently by filtering, evidence hashing, and calendar validation.
    """
    endpoint = today.isoformat()
    return evolve(
        config,
        experience=evolve(config.experience, as_of=config.experience.as_of or endpoint),
        github=evolve(
            config.github, contributions=evolve(config.github.contributions, as_of=config.github.contributions.as_of or endpoint)
        ),
    )
