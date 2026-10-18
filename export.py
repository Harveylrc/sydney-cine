"""Write public/data.json for the page: films, showings and first-seen history.

Rules from DECISIONS.md:
- Late night: a session starting before 05:00 is listed under the previous day
  ("day" in data.json); "start" stays the true time.
- Film type fallback: a showing the venue did not type is "retrospective" if its
  TMDB year is two or more years ago, else "new_release" (None if no year).
- New this week: a film first seen in our data within the last 7 days, not on the
  first day we held its venue (so launch day, or adding a venue, is not "new").
  The page shows it under "new this week" for its new_release showings only.
First-seen dates are carried forward from the previous data.json.
"""

import json
import logging
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from enrich import normalise, search_terms
from models import SYDNEY_TZ, Showing

DATA_PATH = Path(__file__).resolve().parent / "public" / "data.json"
SYDNEY = ZoneInfo(SYDNEY_TZ)
LATE_NIGHT_END = time(5, 0)
NEW_DAYS = 7
RETRO_AGE = 2  # years


def film_id(s: Showing) -> str:
    if s.tmdb_id is not None:
        return f"tmdb:{s.tmdb_id}"
    return "title:" + normalise(search_terms(s.film_title)[0])


def display_day(start: datetime) -> date:
    return start.date() - timedelta(days=1) if start.time() < LATE_NIGHT_END else start.date()


def time_label(start: datetime) -> str:
    return f"{start.hour % 12 or 12}:{start.minute:02d} {'am' if start.hour < 12 else 'pm'}"


def effective_type(s: Showing, this_year: int) -> str | None:
    if s.film_type is not None:
        return s.film_type
    if s.year is None:
        return None
    return "retrospective" if s.year <= this_year - RETRO_AGE else "new_release"


def build_data(showings: list[Showing], previous: dict | None, today: date) -> dict:
    previous = previous or {}
    today_iso = today.isoformat()

    venues = {slug: dict(v) for slug, v in previous.get("venues", {}).items()}
    seen = {fid: dict(by_venue) for fid, by_venue in previous.get("seen", {}).items()}
    films: dict[str, dict] = {}
    rows = []
    for s in sorted(showings, key=lambda s: (s.start, s.film_title)):
        fid = film_id(s)
        venues.setdefault(s.venue_slug, {"name": s.venue_name, "first_seen": today_iso})
        seen.setdefault(fid, {}).setdefault(s.venue_slug, today_iso)
        films.setdefault(
            fid,
            {
                "id": fid,
                "title": search_terms(s.film_title)[0],
                "tmdb_id": s.tmdb_id,
                "year": s.year,
                "director": s.director,
                "rating": s.rating,
                "vote_count": s.vote_count,
            },
        )
        rows.append(
            {
                "film": fid,
                "title": s.film_title,
                "venue": s.venue_slug,
                "start": s.start.isoformat(),
                "day": display_day(s.start).isoformat(),
                "time": time_label(s.start),
                "late": s.start.time() < LATE_NIGHT_END,
                "type": effective_type(s, today.year),
                "attributes": s.attributes,
                "booking_url": s.booking_url,
            }
        )

    new_from = (today - timedelta(days=NEW_DAYS - 1)).isoformat()
    for fid, film in films.items():
        first = min(seen[fid].values())
        film["first_seen"] = first
        # New only if first seen at a venue we already held before that day.
        film["new_this_week"] = first >= new_from and any(
            day == first and day > venues[slug]["first_seen"] for slug, day in seen[fid].items()
        )

    return {
        "generated_at": datetime.now(SYDNEY).isoformat(timespec="seconds"),
        "today": today_iso,
        "venues": venues,
        "films": sorted(films.values(), key=lambda f: f["title"].casefold()),
        "showings": rows,
        "seen": seen,
    }


def load_previous(path: Path = DATA_PATH) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def write(data: dict, path: Path = DATA_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    from enrich import Cache, TMDBClient, enrich, load_overrides, load_token
    from scrapers import hoyts, ritz

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    scraped = ritz.fetch() + hoyts.fetch()
    showings = enrich(scraped, TMDBClient(load_token()), Cache(), load_overrides())
    data = build_data(showings, load_previous(), datetime.now(SYDNEY).date())
    write(data)
    new = sum(f["new_this_week"] for f in data["films"])
    print(
        f"Wrote {DATA_PATH}: {len(data['showings'])} showings, "
        f"{len(data['films'])} films, {new} new this week"
    )
