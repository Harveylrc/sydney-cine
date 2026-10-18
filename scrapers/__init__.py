"""Base class for venue scrapers.

Each venue module subclasses BaseScraper, uses self.get() for every request and
implements fetch() -> list[Showing].
"""

import hashlib
import logging
import re
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import requests

from models import Showing

log = logging.getLogger("scrapers")

USER_AGENT = "sydney-cine/0.1 (+contact in README)"
# Venue listings that are not screenings: dropped by every scraper (DECISIONS
# 2026-10-18). Specific phrases only — "party" or "quiz" alone would catch films
# such as The Party or Quiz Show. Concert films, opera/theatre broadcasts and
# Q&A screenings are screenings and stay.
NON_FILM = re.compile(
    r"\bTrivia\b|\bQuiz Nights?\b|\bDJ (?:Sets?|Nights?)\b|\bDance Party\b"
    r"|\bJazz Lounge\b|\bComedy Club\b",
    re.IGNORECASE,
)
MIN_INTERVAL = 1.0  # seconds between requests to the same host
CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"


MONTHS = {
    name: number
    for number, name in enumerate(
        ["january", "february", "march", "april", "may", "june", "july", "august",
         "september", "october", "november", "december"],
        start=1,
    )
}  # fmt: skip
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
HEADING = re.compile(r"(\w+day)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\w+)", re.IGNORECASE)
# The first heading is today or later; one this far in the past means next year.
STALE = timedelta(days=60)


def heading_dates(headings: list[str], today: date) -> list[date | None]:
    """Day headings without a year ('Sunday 18th October', 'Tuesday 20, October'),
    in date order from today -> dates. A month earlier than the previous heading's
    starts the next year; a first heading long past means next year. The weekday
    is checked and a mismatch logged."""
    dates, year, previous = [], today.year, None
    for text in headings:
        found = HEADING.search(text)
        month = MONTHS.get(found.group(3).lower()) if found else None
        if not month:
            log.warning("Day heading not understood: %r", text)
            dates.append(None)
            continue
        day = int(found.group(2))
        if previous is None:
            if date(year, month, min(day, 28)) < today - STALE:
                year += 1
        elif month < previous.month:
            year += 1
        try:
            on = date(year, month, day)
        except ValueError:  # e.g. 29 February in a year that hasn't one
            log.warning("Day heading %r is not a date in %d", text, year)
            dates.append(None)
            continue
        if WEEKDAYS[on.weekday()] != found.group(1).lower():
            log.warning("Day heading %r is not a %s in %d", text, found.group(1), year)
        dates.append(on)
        previous = on
    return dates


def is_non_film(title: str) -> bool:
    return bool(NON_FILM.search(title))


class BaseScraper:
    # Shared across all scrapers so two venues on one host (e.g. Veezi) still
    # respect the per-host limit.
    _last_request: dict[str, float] = {}

    def __init__(self, cache_dir: Path = CACHE_DIR):
        self.cache_dir = cache_dir
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT

    def get(self, url: str, **kwargs) -> requests.Response:
        """GET url, throttled per host, and save the raw body under cache/."""
        host = urlsplit(url).netloc
        self._wait_for(host)
        response = self.session.get(url, timeout=30, **kwargs)
        BaseScraper._last_request[host] = time.monotonic()
        response.raise_for_status()
        self._save(host, url, response.content)
        return response

    def fetch(self) -> list[Showing]:
        raise NotImplementedError

    def _wait_for(self, host: str) -> None:
        last = BaseScraper._last_request.get(host)
        if last is not None:
            remaining = MIN_INTERVAL - (time.monotonic() - last)
            if remaining > 0:
                time.sleep(remaining)

    def _save(self, host: str, url: str, body: bytes) -> None:
        name = hashlib.sha256(url.encode()).hexdigest()[:16]
        path = self.cache_dir / host / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
