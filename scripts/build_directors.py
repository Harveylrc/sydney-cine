"""Build public/directors.json: the names the page's Director field suggests (B11).

Source (DECISIONS 2026-10-18 "Director list source"): the directors of every TMDB
film with at least MIN_VOTES votes, ranked by their films' total votes, top KEEP
kept, then every director in our data.json not already listed. TMDB's discover
search stops at page 500, so films are fetched one release year at a time.

The nightly job runs it on the 1st of the month, and whenever the published file
is missing:  python -m scripts.build_directors
"""

import json
import logging
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from enrich import TMDBClient, load_token

log = logging.getLogger("directors")

PUBLIC = Path(__file__).resolve().parent.parent / "public"
DIRECTORS_PATH = PUBLIC / "directors.json"
DATA_PATH = PUBLIC / "data.json"
MIN_VOTES = 200
KEEP = 2000
FIRST_YEAR = 1900
MAX_PAGES = 500  # TMDB's discover limit
WORKERS = 8  # parallel credit lookups; TMDB allows ~50 requests a second


def rated_films(client: TMDBClient, this_year: int) -> dict[int, int]:
    """TMDB id -> vote count for every film with at least MIN_VOTES votes."""
    films = {}
    for year in range(FIRST_YEAR, this_year + 1):
        page = 1
        while True:
            found = client._get(
                "/discover/movie",
                sort_by="vote_count.desc",
                primary_release_year=year,
                page=page,
                **{"vote_count.gte": MIN_VOTES},
            )
            films.update((m["id"], m["vote_count"]) for m in found["results"])
            if page >= min(found["total_pages"], MAX_PAGES):
                break
            page += 1
    return films


def directors_of(client: TMDBClient, tmdb_id: int) -> list[str]:
    crew = client._get(f"/movie/{tmdb_id}/credits")["crew"]
    return [c["name"] for c in crew if c["job"] == "Director"]


def rank(films: dict[int, int], credits: dict[int, list[str]], keep: int = KEEP) -> list[str]:
    """Directors by their films' total votes, most first; ties by name."""
    totals = Counter()
    for tmdb_id, names in credits.items():
        for name in names:
            totals[name] += films[tmdb_id]
    return sorted(totals, key=lambda name: (-totals[name], name))[:keep]


def our_directors(data: dict | None) -> list[str]:
    names = set()
    for film in (data or {}).get("films", []):
        names.update(n for n in (film.get("director") or "").split(", ") if n)
    return sorted(names)


def build(
    client: TMDBClient, this_year: int, data: dict | None, workers: int = WORKERS
) -> list[str]:
    films = rated_films(client, this_year)
    log.info("%d TMDB films with at least %d votes", len(films), MIN_VOTES)
    with ThreadPoolExecutor(workers) as pool:
        credits = dict(zip(films, pool.map(lambda i: directors_of(client, i), films), strict=True))
    ranked = rank(films, credits)
    listed = set(ranked)
    return ranked + [name for name in our_directors(data) if name not in listed]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    data = json.loads(DATA_PATH.read_text(encoding="utf-8")) if DATA_PATH.exists() else None
    names = build(TMDBClient(load_token()), date.today().year, data)
    if len(names) < KEEP // 2:  # TMDB answered oddly: keep last month's list
        sys.exit(f"Only {len(names)} directors found; not writing {DIRECTORS_PATH}")
    DIRECTORS_PATH.write_text(json.dumps(names, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {DIRECTORS_PATH}: {len(names)} directors")
