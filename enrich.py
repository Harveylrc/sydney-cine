"""TMDB enrichment: fill tmdb_id, year, director and rating on scraped Showings.

Matching order: showings that share a vista_movie_id are looked up once for the
whole group; otherwise each distinct title is searched on TMDB and only an exact
title match is accepted (within a year of the venue's year when the title carries
one, e.g. "Léon: The Professional (1994)"). Every lookup, hit
or miss, is cached in SQLite so a title is only ever queried once. Unmatched
showings are logged and returned unchanged, never dropped.
"""

import logging
import os
import re
import sqlite3
import time
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path

import requests

from models import Showing

log = logging.getLogger("enrich")

API = "https://api.themoviedb.org/3"
DB_PATH = Path(__file__).resolve().parent / "cache" / "tmdb.sqlite"
ENV_PATH = Path(__file__).resolve().parent / ".env"

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
    def __init__(self, token: str, session: requests.Session | None = None):
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

    def find(self, title: str, year: int | None) -> Match:
        """Best TMDB result whose title matches exactly (ignoring case and
        punctuation) and, if the venue gave a year, is within a year of it —
        venues often give the premiere year, TMDB the first release."""
        results = self._get("/search/movie", query=title, include_adult="false")["results"]
        wanted = normalise(title)
        candidates = [
            r
            for r in results
            if wanted in (normalise(r.get("title", "")), normalise(r.get("original_title", "")))
            and (year is None or abs((release_year(r) or 0) - year) <= 1)
        ]
        if not candidates:
            return Match(tmdb_id=None)
        movie = self._get(f"/movie/{candidates[0]['id']}", append_to_response="credits")
        directors = [c["name"] for c in movie["credits"]["crew"] if c["job"] == "Director"]
        return Match(
            tmdb_id=movie["id"],
            year=release_year(movie),
            director=", ".join(directors) or None,
            rating=movie["vote_average"] if movie.get("vote_count") else None,
        )


class Cache:
    def __init__(self, path: Path = DB_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS lookups (
                key TEXT PRIMARY KEY,  -- "vista:HO000…" or "title:<title>|<year>"
                tmdb_id INTEGER, year INTEGER, director TEXT, rating REAL
            );
            """
        )

    def get(self, key: str) -> Match | None:
        row = self.db.execute(
            "SELECT tmdb_id, year, director, rating FROM lookups WHERE key = ?", (key,)
        ).fetchone()
        return Match(*row) if row else None

    def put(self, key: str, match: Match) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO lookups VALUES (?, ?, ?, ?, ?)",
            (key, match.tmdb_id, match.year, match.director, match.rating),
        )
        self.db.commit()


def lookup_key(s: Showing) -> str:
    """Showings with the same key share one TMDB lookup."""
    if s.vista_movie_id:
        return f"vista:{s.vista_movie_id}"
    title, year = search_terms(s.film_title)
    return f"title:{title.casefold()}|{year or ''}"


def enrich(showings: list[Showing], client: TMDBClient, cache: Cache) -> list[Showing]:
    def lookup(key: str, film_title: str) -> Match:
        if (match := cache.get(key)) is None:
            match = client.find(*search_terms(film_title))
            cache.put(key, match)
        return match

    matches: dict[str, Match] = {}
    for s in showings:
        key = lookup_key(s)
        if key not in matches:
            matches[key] = lookup(key, s.film_title)
            if matches[key].tmdb_id is None:
                log.warning("No TMDB match for %r (%s)", s.film_title, key)

    enriched = []
    for s in showings:
        match = matches[lookup_key(s)]
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
    results = enrich(ritz.fetch(), TMDBClient(load_token()), Cache())
    seen = set()
    for s in results:
        if s.film_title not in seen:
            seen.add(s.film_title)
            print(f"{s.film_title!r:60} {s.tmdb_id} {s.year} {s.director} {s.rating}")
    matched = sum(s.tmdb_id is not None for s in results)
    print(f"{matched}/{len(results)} showings matched, {len(seen)} films")
