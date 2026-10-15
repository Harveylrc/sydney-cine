"""Shared data model. Every scraper's fetch() returns list[Showing]."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Showing:
    """One screening of one film at one venue, as scraped (before enrichment)."""

    venue: str
    title: str
    starts_at: datetime  # local Sydney time, timezone-aware
    booking_url: str | None = None
