"""TMDB enrichment: fill tmdb_id, year, director and rating on scraped Showings.

Matching order (policy in DECISIONS.md):
1. tmdb_overrides.csv: a hand-kept map of exact venue title -> TMDB id or "none".
2. Showings that share a vista_movie_id are looked up once for the whole group.
3. Otherwise the cleaned title is searched on TMDB and only an exact title match
   is accepted (within a year of the venue's year when the title carries one,
   e.g. "Léon: The Professional (1994)"). With no year, a new_release or festival
   showing prefers an exact match released in the last RECENT_YEARS years.
Every lookup, hit or miss, is cached in SQLite so it is only ever made once.
Unmatched showings are logged and returned unchanged, never dropped.
"""

import csv
import logging
import os
import re
import sqlite3
import time
import unicodedata
from dataclasses import dataclass, replace
from datetime import date
from functools import partial
from pathlib import Path

import requests

from models import Showing

log = logging.getLogger("enrich")

API = "https://api.themoviedb.org/3"
DB_PATH = Path(__file__).resolve().parent / "cache" / "tmdb.sqlite"
ENV_PATH = Path(__file__).resolve().parent / ".env"
OVERRIDES_PATH = Path(__file__).resolve().parent / "tmdb_overrides.csv"

# No-year tiebreak: these showings prefer an exact match from the last 3 years.
RECENT_YEARS = 3
PREFER_RECENT_TYPES = {"new_release", "festival"}

# Venue decorations that are not part of the film's title.
TITLE_PREFIX = re.compile(r"^(?:\d{2}mm\s+|(?:JIFF|SFF):\s*)+", re.IGNORECASE)
TITLE_SUFFIX = re.compile(r"\s+[-–]\s+(?:Digital|\d{2}mm)$", re.IGNORECASE)
TITLE_YEAR = re.compile(r"\s*\((\d{4})\)$")


@dataclass(frozen=True)
class Match:
    tmdb_id: int | None  # None: searched, nothing found
    year: int | None = None
    director: str | None = None
    rating: float | None = None
    vote_count: int | None = None


def search_terms(film_title: str) -> tuple[str, int | None]:
    """Strip venue decorations; pull a trailing "(YYYY)" out as the year."""
    title = TITLE_PREFIX.sub("", film_title.strip())
    title = TITLE_SUFFIX.sub("", title)
    year = None
    if m := TITLE_YEAR.search(title):
        year = int(m.group(1))
        title = title[: m.start()]
    return title.strip(), year


def normalise(title: str) -> str:
    """Lowercase, no accents, letters and digits only:
    "De Gaulle: Résistance" -> "degaulleresistance"."""
    decomposed = unicodedata.normalize("NFKD", title.casefold())
    return "".join(ch for ch in decomposed if ch.isalnum())


def release_year(movie: dict) -> int | None:
    release = movie.get("release_date") or ""
    return int(release[:4]) if release[:4].isdigit() else None


class TMDBClient:
    def __init__(
        self, token: str, session: requests.Session | None = None, this_year: int | None = None
    ):
        self.this_year = this_year or date.today().year
        self.session = session or requests.Session()
        self.session.headers["Authorization"] = f"Bearer {token}"
        self.session.headers["Accept"] = "application/json"

    def _get(self, path: str, **params) -> dict:
        for _ in range(3):
            response = self.session.get(f"{API}{path}", params=params, timeout=30)
            if response.status_code != 429:
                response.raise_for_status()
                return response.json()
            time.sleep(float(response.headers.get("Retry-After", 1)))
        response.raise_for_status()
        return response.json()

    def find(self, title: str, year: int | None, prefer_recent: bool = False) -> Match:
        """Best TMDB result whose title matches exactly (ignoring case and
        punctuation) and, if the venue gave a year, is within a year of it —
        venues often give the premiere year, TMDB the first release. With no
        year and prefer_recent, the first exact match from the last
        RECENT_YEARS years wins; failing that, TMDB's first exact match."""
        results = self._get("/search/movie", query=title, include_adult="false")["results"]
        wanted = normalise(title)
        candidates = [
            r
            for r in results
            if wanted in (normalise(r.get("title", "")), normalise(r.get("original_title", "")))
            and (year is None or abs((release_year(r) or 0) - year) <= 1)
        ]
        if prefer_recent and year is None:
            cutoff = self.this_year - RECENT_YEARS
            recent = [r for r in candidates if (release_year(r) or 0) >= cutoff]
            candidates = recent or candidates
        if not candidates:
            return Match(tmdb_id=None)
        return self.details(candidates[0]["id"])

    def details(self, tmdb_id: int) -> Match:
        movie = self._get(f"/movie/{tmdb_id}", append_to_response="credits")
        directors = [c["name"] for c in movie["credits"]["crew"] if c["job"] == "Director"]
        return Match(
            tmdb_id=movie["id"],
            year=release_year(movie),
            director=", ".join(directors) or None,
            rating=movie["vote_average"] if movie.get("vote_count") else None,
            vote_count=movie.get("vote_count"),
        )


class Cache:
    def __init__(self, path: Path = DB_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS lookups (
                -- "vista:HO000…", "title:<title>|<year>[|recent]" or "tmdb:<id>"
                key TEXT PRIMARY KEY,
                tmdb_id INTEGER, year INTEGER, director TEXT, rating REAL, vote_count INTEGER
            );
            """
        )

    def get(self, key: str) -> Match | None:
        row = self.db.execute(
            "SELECT tmdb_id, year, director, rating, vote_count FROM lookups WHERE key = ?",
            (key,),
        ).fetchone()
        return Match(*row) if row else None

    def put(self, key: str, match: Match) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO lookups VALUES (?, ?, ?, ?, ?, ?)",
            (key, match.tmdb_id, match.year, match.director, match.rating, match.vote_count),
        )
        self.db.commit()


def prefers_recent(s: Showing) -> bool:
    return s.film_type in PREFER_RECENT_TYPES and search_terms(s.film_title)[1] is None


def lookup_key(s: Showing) -> str:
    """Showings with the same key share one TMDB lookup."""
    if s.vista_movie_id:
        return f"vista:{s.vista_movie_id}"
    title, year = search_terms(s.film_title)
    return f"title:{title.casefold()}|{year or ''}" + ("|recent" if prefers_recent(s) else "")


def load_overrides(path: Path = OVERRIDES_PATH) -> dict[str, int | None]:
    """venue_title -> TMDB id, or None for "none" (deliberately unmatched)."""
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as f:
        return {
            row["venue_title"]: None if row["tmdb_id"].strip() == "none" else int(row["tmdb_id"])
            for row in csv.DictReader(f)
        }


def enrich(
    showings: list[Showing],
    client: TMDBClient,
    cache: Cache,
    overrides: dict[str, int | None] | None = None,
) -> list[Showing]:
    overrides = overrides or {}
    matches: dict[str, Match] = {}

    def resolve(s: Showing) -> Match:
        if s.film_title in overrides:
            tmdb_id = overrides[s.film_title]
            if tmdb_id is None:
                return Match(tmdb_id=None)  # deliberate: not a miss, not logged
            key = f"tmdb:{tmdb_id}"
            fetch = partial(client.details, tmdb_id)
        else:
            key = lookup_key(s)
            fetch = partial(
                client.find, *search_terms(s.film_title), prefer_recent=prefers_recent(s)
            )
        if key not in matches:
            if (match := cache.get(key)) is None:
                match = fetch()
                cache.put(key, match)
            matches[key] = match
            if match.tmdb_id is None:
                log.warning("No TMDB match for %r (%s)", s.film_title, key)
        return matches[key]

    enriched = []
    for s in showings:
        match = resolve(s)
        if match.tmdb_id is None:
            enriched.append(s)
        else:
            enriched.append(
                replace(
                    s,
                    tmdb_id=match.tmdb_id,
                    year=match.year,
                    director=match.director,
                    rating=match.rating,
                    vote_count=match.vote_count,
                )
            )
    return enriched


def load_token(env_path: Path = ENV_PATH) -> str:
    if token := os.environ.get("TMDB_API_KEY"):
        return token
    for line in env_path.read_text().splitlines():
        name, _, value = line.partition("=")
        if name.strip() == "TMDB_API_KEY" and value.strip():
            return value.strip()
    raise SystemExit("TMDB_API_KEY not set (environment or .env)")


if __name__ == "__main__":
    from scrapers import ritz

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    results = enrich(ritz.fetch(), TMDBClient(load_token()), Cache(), load_overrides())
    seen = set()
    for s in results:
        if s.film_title not in seen:
            seen.add(s.film_title)
            print(f"{s.film_title!r:60} {s.tmdb_id} {s.year} {s.director} {s.rating}")
    matched = sum(s.tmdb_id is not None for s in results)
    print(f"{matched}/{len(results)} showings matched, {len(seen)} films")
