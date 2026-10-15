"""Shared data model. Every scraper's fetch() returns list[Showing]."""

from dataclasses import dataclass, field
from datetime import datetime

SYDNEY_TZ = "Australia/Sydney"
FILM_TYPES = {"new_release", "retrospective", "festival", "special"}


@dataclass(frozen=True)
class Showing:
    """One screening of one film at one venue.

    Scrapers fill the venue/session fields; enrichment (B3) fills tmdb_id, year,
    director and rating.
    """

    venue_slug: str
    venue_name: str
    film_title: str
    start: datetime  # timezone-aware, Australia/Sydney
    session_id: str | None = None
    booking_url: str | None = None
    attributes: list[str] = field(default_factory=list)  # e.g. "70mm", "Captions", "NFT"
    film_type: str | None = None  # one of FILM_TYPES, as the venue labels it
    vista_movie_id: str | None = None  # "HO000…" — shared by Hoyts, Palace, Orpheum
    tmdb_id: int | None = None
    year: int | None = None
    director: str | None = None
    rating: float | None = None

    def __post_init__(self):
        if self.start.tzinfo is None or str(self.start.tzinfo) != SYDNEY_TZ:
            raise ValueError(f"start must be in {SYDNEY_TZ}, got {self.start!r}")
        if self.film_type is not None and self.film_type not in FILM_TYPES:
            raise ValueError(
                f"film_type must be one of {sorted(FILM_TYPES)}, got {self.film_type!r}"
            )
