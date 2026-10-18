"""Hand-kept sessions for venues we may not scrape (B13a-ii; DECISIONS 2026-10-19).

Each manual/<venue>.yaml holds one venue's sessions, typed in (usually via
scripts/paste_to_manual.py from text copied in Harvey's own browser):

    venue: sydney-cinematheque          # slug, as in venues.yaml
    name: Sydney Cinémathèque
    source: https://…                   # the page the sessions were copied from
    updated: 2026-10-19                 # when they were last copied
    type: retrospective                 # optional default film type for the file
    sessions:
      - date: 2026-10-22
        time: "19:00"                   # 24-hour, Sydney time
        title: Vivre sa vie
        year: 1962                      # optional, helps the TMDB match
        director: Jean-Luc Godard       # optional
        type: retrospective             # optional, overrides the file's
        tags: [35mm]                    # optional
        url: https://…                  # optional booking / information page

Sessions already started are ignored, so an old file simply runs dry: the venue
then has no sessions and counts as uncovered.
"""

import logging
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from models import FILM_TYPES, SYDNEY_TZ, Showing

log = logging.getLogger("scrapers")

MANUAL_DIR = Path(__file__).resolve().parent.parent / "manual"
SYDNEY = ZoneInfo(SYDNEY_TZ)


def clock(value) -> time:
    """A session time: "19:00", "7:05", or 1140, which is how YAML reads an
    unquoted 19:00 (19 × 60 minutes)."""
    if isinstance(value, int):
        return time(value // 60, value % 60)
    hours, _, minutes = str(value).strip().partition(":")
    return time(int(hours), int(minutes))


def parse_file(data: dict, now: datetime) -> list[Showing]:
    default_type = data.get("type")
    showings = []
    for entry in data.get("sessions") or []:
        day = (
            entry["date"] if isinstance(entry["date"], date) else date.fromisoformat(entry["date"])
        )
        start = datetime.combine(day, clock(entry["time"]), tzinfo=SYDNEY)
        if start < now:
            continue
        film_type = entry.get("type", default_type)
        if film_type is not None and film_type not in FILM_TYPES:
            raise ValueError(f"{data['venue']}: {entry['title']!r} has unknown type {film_type!r}")
        title = str(entry["title"]).strip()
        if entry.get("year"):  # "(1962)": enrich reads it as the year to match
            title = f"{title} ({entry['year']})"
        showings.append(
            Showing(
                venue_slug=data["venue"],
                venue_name=data["name"],
                film_title=title,
                start=start,
                booking_url=entry.get("url") or data.get("source"),
                attributes=list(entry.get("tags") or []),
                film_type=film_type,
                venue_director=entry.get("director"),
            )
        )
    return showings


def load(directory: Path = MANUAL_DIR) -> list[dict]:
    return [
        yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.yaml"))
    ]


def fetch(directory: Path = MANUAL_DIR, now: datetime | None = None) -> list[Showing]:
    now = now or datetime.now(SYDNEY)
    showings = []
    for data in load(directory):
        found = parse_file(data, now)
        log.info(
            "Manual %s (updated %s): %d upcoming sessions",
            data["venue"],
            data.get("updated"),
            len(found),
        )
        showings.extend(found)
    return showings
