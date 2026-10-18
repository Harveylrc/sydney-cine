"""Write public/data.json for the page (films, showings and first-seen history) and
public/films.json for a film's expanded row.

Rules from DECISIONS.md:
- Late night: a session starting before 05:00 is listed under the previous day
  ("day" in data.json); "start" stays the true time.
- Film type fallback: a showing the venue did not type is "retrospective" if its
  TMDB year is two or more years ago, else "new_release" (None if no year).
- New this week: a film first seen in our data within the last 7 days, not on the
  first day we held its venue (so launch day, or adding a venue, is not "new").
  The page shows it under "new this week" for its new_release showings only.
- Horizon: only showings whose display day is within HORIZON_DAYS of today, for
  every venue (Hoyts lists ~10 weeks ahead). A film is first seen when it enters
  the horizon.
- "Audio Description" and "Closed Captions" are dropped from attributes: almost
  every chain session has them, so they are noise. "Open Captions" stays.
- Regions (B12): each venue's regions come from venues.yaml (venue -> LGA ->
  one of REGIONS; a venue may list more than one, e.g. Moore Park is City and
  East). Every session carries its venue's "regions" list, and the top-level
  "regions" lists those that have sessions, in REGIONS order, for the filter.
- Partial days (B10d): a day with fewer than half the busiest day's sessions is
  "partial": the chains publish the next Thu–Wed week around Tuesday/Wednesday,
  and until then the days after the current week hold only advance sessions.
- Expanded row (B10c): poster_path and runtime from TMDB; with no TMDB runtime,
  the first venue running time we saw. They go in films.json, which the page
  loads the first time a row is opened, so data.json stays small. No synopsis.
First-seen dates are carried forward from the previous data.json.
"""

import json
import logging
import os
from collections import Counter
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from enrich import normalise, search_terms
from models import SYDNEY_TZ, Showing

log = logging.getLogger("export")

DATA_PATH = Path(__file__).resolve().parent / "public" / "data.json"
FILMS_PATH = DATA_PATH.with_name("films.json")
VENUES_PATH = Path(__file__).resolve().parent / "venues.yaml"
REGIONS = (  # DECISIONS 2026-10-18 "Regions", in the page's order
    "City",
    "East",
    "Inner West",
    "North",
    "Parramatta & Hills",
    "Outer West",
    "South West",
    "St George & Sutherland",
)
SYDNEY = ZoneInfo(SYDNEY_TZ)
LATE_NIGHT_END = time(5, 0)
NEW_DAYS = 7
RETRO_AGE = 2  # years
HORIZON_DAYS = 14
HIDDEN_ATTRIBUTES = {"Audio Description", "Closed Captions"}


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


def build_data(
    showings: list[Showing],
    previous: dict | None,
    today: date,
    venue_info: dict[str, dict] | None = None,
) -> dict:
    """venue_info: slug -> venues.yaml entry (load_venues())."""
    previous = previous or {}
    venue_info = venue_info or {}
    today_iso = today.isoformat()

    venues = {slug: dict(v) for slug, v in previous.get("venues", {}).items()}
    seen = {fid: dict(by_venue) for fid, by_venue in previous.get("seen", {}).items()}
    films: dict[str, dict] = {}
    rows = []
    for title, venue in sorted(
        {(s.film_title, s.venue_name) for s in showings if s.is_film is False}
    ):
        log.info("Dropped, not a film: %r at %s", title, venue)
    showings = [s for s in showings if s.is_film is not False]
    last_day = today + timedelta(days=HORIZON_DAYS - 1)
    showings = [s for s in showings if today <= display_day(s.start) <= last_day]
    for s in sorted(showings, key=lambda s: (s.start, s.film_title)):
        fid = film_id(s)
        venue = venues.setdefault(s.venue_slug, {"name": s.venue_name, "first_seen": today_iso})
        regions = venue_info.get(s.venue_slug, {}).get("regions", [])
        venue["regions"] = regions
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
                "regions": regions,
                "start": s.start.isoformat(),
                "day": display_day(s.start).isoformat(),
                "time": time_label(s.start),
                "late": s.start.time() < LATE_NIGHT_END,
                "type": effective_type(s, today.year),
                "attributes": [a for a in s.attributes if a not in HIDDEN_ATTRIBUTES],
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
        "days": day_status(rows),
        "regions": [r for r in REGIONS if any(r in row["regions"] for row in rows)],
        "seen": seen,
    }


def load_venues(path: Path = VENUES_PATH) -> dict[str, dict]:
    """slug -> {slug, name, lga, regions, screens} from venues.yaml, where "region"
    is one region or a list of them; it comes back as the list "regions"."""
    entries = yaml.safe_load(path.read_text(encoding="utf-8"))
    venues = {}
    for entry in entries:
        region = entry.pop("region")
        entry["regions"] = region if isinstance(region, list) else [region]
        for name in entry["regions"]:
            if name not in REGIONS:
                raise ValueError(f"{path.name}: {entry['slug']} has unknown region {name!r}")
        venues[entry["slug"]] = entry
    return venues


def unplaced_venues(showings: list[Showing], venue_info: dict[str, dict]) -> list[str]:
    """Venues with sessions but no venues.yaml entry (so no region)."""
    return sorted({s.venue_slug for s in showings} - set(venue_info))


def day_status(rows: list[dict]) -> dict[str, dict]:
    """Display day -> {"sessions": n, "partial": bool}, in day order."""
    counts = Counter(row["day"] for row in rows)
    busiest = max(counts.values(), default=0)
    return {day: {"sessions": n, "partial": n < busiest / 2} for day, n in sorted(counts.items())}


def build_film_details(showings: list[Showing], data: dict, details: dict[int, dict]) -> dict:
    """films.json: film id -> {poster_path, runtime} for data's films, with empty
    fields left out. details: tmdb id -> enrich.film_details() fields."""
    wanted = {film["id"] for film in data["films"]}
    panel: dict[str, dict] = {}
    for s in sorted(showings, key=lambda s: (s.start, s.film_title)):
        fid = film_id(s)
        if fid not in wanted:
            continue
        found = details.get(s.tmdb_id, {})
        entry = panel.setdefault(fid, {k: found.get(k) for k in ("poster_path", "runtime")})
        if not entry.get("runtime") and s.runtime_min:
            entry["runtime"] = s.runtime_min
    cleaned = {fid: {k: v for k, v in entry.items() if v} for fid, entry in panel.items()}
    return {fid: entry for fid, entry in cleaned.items() if entry}


def scrape_all(scrapers) -> list[Showing]:
    """Run each scraper module's fetch(); one venue failing (site down, markup
    changed) is logged and skipped so the rest still publish. All failing is fatal."""
    showings, failed = [], []
    for scraper in scrapers:
        name = scraper.__name__.rsplit(".", 1)[-1]
        try:
            found = scraper.fetch()
        except Exception:
            log.exception("Scraper %s failed; its venues are missing tonight", name)
            failed.append(name)
            continue
        log.info("Scraper %s: %d showings", name, len(found))
        showings.extend(found)
    if failed and os.environ.get("GITHUB_ACTIONS"):
        print(f"::warning::Scrapers failed: {', '.join(failed)}")  # shown on the run page
    if len(failed) == len(scrapers):
        raise SystemExit("Every scraper failed; not writing data.json")
    return showings


def load_previous(path: Path = DATA_PATH) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def write(data: dict, path: Path = DATA_PATH) -> None:
    """data.json, or films.json with path=FILMS_PATH."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    from coverage import coverage
    from enrich import (
        Cache,
        TMDBClient,
        claude_chooser,
        enrich,
        film_details,
        load_overrides,
        load_token,
        report,
    )
    from scrapers import event, golden_age, hoyts, orpheum, palace, ritz, roseville

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    scrapers = (ritz, hoyts, palace, orpheum, golden_age, roseville, event)
    scraped = scrape_all(scrapers)
    chooser = claude_chooser()
    client, cache = TMDBClient(load_token()), Cache()
    showings = enrich(scraped, client, cache, load_overrides(), chooser)
    report(chooser)
    details = film_details((s.tmdb_id for s in showings if s.tmdb_id), client, cache)
    venue_info = load_venues()
    for slug in unplaced_venues(showings, venue_info):
        log.warning("Venue %s is not in venues.yaml: no region", slug)
    data = build_data(showings, load_previous(), datetime.now(SYDNEY).date(), venue_info)
    data["coverage"] = coverage(venue_info, data["showings"])
    write(data)
    write(build_film_details(showings, data, details), FILMS_PATH)
    new = sum(f["new_this_week"] for f in data["films"])
    print(
        f"Wrote {DATA_PATH}: {len(data['showings'])} showings, "
        f"{len(data['films'])} films, {new} new this week"
    )
