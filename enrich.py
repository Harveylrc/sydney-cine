"""TMDB enrichment: fill tmdb_id, year, director and rating on scraped Showings.

Matching order (policy in DECISIONS.md):
1. tmdb_overrides.csv: a hand-kept map of exact venue title -> TMDB id or "none".
2. Showings that share a vista_movie_id within one chain are looked up once for
   the whole group. Vista ids are per chain (Palace's HO00011213 is not Hoyts'),
   so the key includes the chain: the first part of venue_slug ("hoyts", "palace").
3. Otherwise the cleaned title is searched on TMDB and only an exact title match
   is accepted (within a year of the venue's year when the title carries one,
   e.g. "Léon: The Professional (1994)"). With no year, a new_release or festival
   showing prefers an exact match released in the last RECENT_YEARS years.
4. When the rules are unsure — several exact-title candidates, or none — and an
   ANTHROPIC_API_KEY is set, Claude picks one of up to MAX_CANDIDATES TMDB
   results (or "none") from the venue title, film type and tags. At most
   MAX_CLAUDE_CALLS per run; when Claude can't answer, step 3's rules decide
   and that answer is not cached, so Claude is asked again next run.
Every final lookup, hit or miss, is cached in SQLite so it is only made once.
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

import anthropic
import requests

from models import Showing

log = logging.getLogger("enrich")

API = "https://api.themoviedb.org/3"
DB_PATH = Path(__file__).resolve().parent / "cache" / "tmdb.sqlite"
ENV_PATH = Path(__file__).resolve().parent / ".env"
OVERRIDES_PATH = Path(__file__).resolve().parent / "tmdb_overrides.csv"

CLAUDE_MODEL = "claude-sonnet-5-5"
MAX_CLAUDE_CALLS = 200  # per run: hard budget guard
MAX_CANDIDATES = 8
CLAUDE_MAX_TOKENS = 2000  # room to think before the final "Answer:" line
OVERVIEW_CHARS = 300
SYNOPSIS_CHARS = 800

# No-year tiebreak: these showings prefer an exact match from the last 3 years.
RECENT_YEARS = 3
PREFER_RECENT_TYPES = {"new_release", "festival"}

# Venue decorations that are not part of the film's title.
# "35mm ", "JIFF: ", "(LFF) ", and Palace festival codes such as "BFF26 ", "GFF26 ".
TITLE_PREFIX = re.compile(
    r"^(?:\d{2}mm\s+|(?:JIFF|SFF):\s*|\(LFF\)\s*|[A-Z]{1,4}FF\d{2}\s+)+", re.IGNORECASE
)
TITLE_SUFFIX = re.compile(
    r"\s+[-–]\s+(?:Digital|\d{2}mm|\d+(?:st|nd|rd|th) Anniversary)$"  # " - Digital"
    r"|\s*\([^()]*,\s*Eng Sub\)$"  # Hoyts language: " (Hindi, Eng Sub)"
    r"|[\s:(]+Encore\)?$",  # Hoyts re-runs: ": Encore", " (Encore)"
    re.IGNORECASE,
)
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
    while (stripped := TITLE_SUFFIX.sub("", title)) != title:
        title = stripped
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
        self._movies: dict[int, dict] = {}

    def _get(self, path: str, **params) -> dict:
        for _ in range(3):
            response = self.session.get(f"{API}{path}", params=params, timeout=30)
            if response.status_code != 429:
                response.raise_for_status()
                return response.json()
            time.sleep(float(response.headers.get("Retry-After", 1)))
        response.raise_for_status()
        return response.json()

    def search(self, title: str, year: int | None) -> tuple[list[dict], list[dict]]:
        """(exact, results): TMDB's results in its order, and those whose title
        matches exactly (ignoring case and punctuation) and, if the venue gave a
        year, are within a year of it — venues often give the premiere year,
        TMDB the first release."""
        results = self._get("/search/movie", query=title, include_adult="false")["results"]
        wanted = normalise(title)
        exact = [
            r
            for r in results
            if wanted in (normalise(r.get("title", "")), normalise(r.get("original_title", "")))
            and (year is None or abs((release_year(r) or 0) - year) <= 1)
        ]
        return exact, results

    def find(self, title: str, year: int | None, prefer_recent: bool = False) -> Match:
        """The rules alone: see pick()."""
        return self.pick(self.search(title, year)[0], year, prefer_recent)

    def rule_choice(
        self, candidates: list[dict], year: int | None, prefer_recent: bool
    ) -> dict | None:
        """With no year and prefer_recent, the first exact match from the last
        RECENT_YEARS years wins; failing that, TMDB's first exact match."""
        if prefer_recent and year is None:
            cutoff = self.this_year - RECENT_YEARS
            recent = [r for r in candidates if (release_year(r) or 0) >= cutoff]
            candidates = recent or candidates
        return candidates[0] if candidates else None

    def pick(self, candidates: list[dict], year: int | None, prefer_recent: bool) -> Match:
        chosen = self.rule_choice(candidates, year, prefer_recent)
        return self.details(chosen["id"]) if chosen else Match(tmdb_id=None)

    def movie(self, tmdb_id: int) -> dict:
        if tmdb_id not in self._movies:
            self._movies[tmdb_id] = self._get(f"/movie/{tmdb_id}", append_to_response="credits")
        return self._movies[tmdb_id]

    def details(self, tmdb_id: int) -> Match:
        movie = self.movie(tmdb_id)
        return Match(
            tmdb_id=movie["id"],
            year=release_year(movie),
            director=directors(movie),
            rating=movie["vote_average"] if movie.get("vote_count") else None,
            vote_count=movie.get("vote_count"),
        )

    def describe(self, result: dict) -> dict:
        """A search result as Claude sees it: title, year, director, runtime, overview."""
        movie = self.movie(result["id"])
        return {
            "tmdb_id": movie["id"],
            "title": movie.get("title", ""),
            "original_title": movie.get("original_title", ""),
            "year": release_year(movie),
            "director": directors(movie),
            "runtime": movie.get("runtime") or None,
            "overview": (movie.get("overview") or "")[:OVERVIEW_CHARS],
        }


def directors(movie: dict) -> str | None:
    names = [c["name"] for c in movie["credits"]["crew"] if c["job"] == "Director"]
    return ", ".join(names) or None


ANSWER = re.compile(r"answer:\s*\**\s*(\d+|none)", re.IGNORECASE)


class ChooserUnavailable(Exception):
    """Claude gave no usable answer (budget spent, API error, odd reply)."""


class ClaudeChooser:
    """Asks Claude which TMDB candidate a venue's screening is."""

    SYSTEM = (
        "You match Sydney cinema listings to The Movie Database (TMDB). Venue titles may "
        "carry festival codes (e.g. BFF26, JFF26), formats, languages or anniversary notes. "
        "Decide which candidate is the film being screened. When the title rules have a "
        "choice, keep it unless the venue's description, the year or the running time "
        "contradicts it. When they have none, pick the candidate the evidence supports, or "
        "none rather than guess. End your reply with one line: "
        "'Answer: <tmdb_id>' or 'Answer: none'."
    )

    def __init__(self, client, model: str = CLAUDE_MODEL, max_calls: int = MAX_CLAUDE_CALLS):
        self.client, self.model, self.max_calls = client, model, max_calls
        self.calls = 0
        self.answers = {"matched": 0, "none": 0}
        self._budget_logged = False

    def choose(
        self, s: Showing, candidates: list[dict], rules_pick: int | None = None
    ) -> int | None:
        if self.calls >= self.max_calls:
            if not self._budget_logged:
                log.warning("Claude budget of %d calls used; rules decide the rest", self.max_calls)
                self._budget_logged = True
            raise ChooserUnavailable("budget")
        self.calls += 1
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=CLAUDE_MAX_TOKENS,
                system=self.SYSTEM,
                messages=[{"role": "user", "content": prompt(s, candidates, rules_pick)}],
            )
            # Thinking blocks may come first; the answer is in the text blocks.
            reply = "\n".join(b.text for b in response.content if b.type == "text")
        except Exception as error:  # network or API error
            log.warning("Claude call failed for %r: %s", s.film_title, error)
            raise ChooserUnavailable("error") from error
        answers = ANSWER.findall(reply)
        ids = {c["tmdb_id"] for c in candidates}
        if not answers or (answers[-1].lower() != "none" and int(answers[-1]) not in ids):
            log.warning("Claude reply for %r has no usable answer: %r", s.film_title, reply[-80:])
            raise ChooserUnavailable("reply")
        if answers[-1].lower() == "none":
            self.answers["none"] += 1
            return None
        self.answers["matched"] += 1
        return int(answers[-1])


def prompt(s: Showing, candidates: list[dict], rules_pick: int | None = None) -> str:
    lines = [
        "A Sydney cinema lists this screening:",
        f"Title: {s.film_title}",
        f"Type: {(s.film_type or 'not given').replace('_', ' ')}",
        f"Tags: {', '.join(s.attributes) or 'none'}",
    ]
    if s.runtime_min:
        lines.append(f"Running time: {s.runtime_min} min")
    if s.venue_synopsis:
        lines.append(f"Venue's description: {' '.join(s.venue_synopsis.split())[:SYNOPSIS_CHARS]}")
    lines += [
        "",
        "Which of these TMDB entries is the film being screened?",
    ]
    for c in candidates:
        also = (
            f" (original title: {c['original_title']})" if c["original_title"] != c["title"] else ""
        )
        runtime = f", {c['runtime']} min" if c["runtime"] else ""
        lines.append(
            f"- tmdb_id {c['tmdb_id']}: {c['title']}{also}, {c['year'] or 'year unknown'}"
            f"{runtime}, directed by {c['director'] or 'unknown'}. {c['overview']}"
        )
    choice = f"tmdb_id {rules_pick}" if rules_pick else "no choice"
    lines += ["", f"The title rules' choice: {choice}."]
    lines += ["End with 'Answer: <tmdb_id>' or 'Answer: none'."]
    return "\n".join(lines)


def claude_chooser(env_path: Path = ENV_PATH) -> ClaudeChooser | None:
    """A chooser if ANTHROPIC_API_KEY is set, else None (logged once per run)."""
    key = load_env("ANTHROPIC_API_KEY", env_path)
    if not key:
        log.info("ANTHROPIC_API_KEY not set: TMDB matching uses the rules only")
        return None
    return ClaudeChooser(anthropic.Anthropic(api_key=key))


class Cache:
    def __init__(self, path: Path = DB_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS lookups (
                -- "vista:<chain>:HO000…", "title:<title>|<year>[|recent]" or "tmdb:<id>"
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
        chain = s.venue_slug.split("-")[0]
        return f"vista:{chain}:{s.vista_movie_id}"
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
    chooser: ClaudeChooser | None = None,
) -> list[Showing]:
    overrides = overrides or {}
    matches: dict[str, Match] = {}

    def look_up(s: Showing) -> tuple[Match, bool]:
        """(match, final). Not final when Claude should have decided but couldn't."""
        title, year = search_terms(s.film_title)
        exact, results = client.search(title, year)
        pool = (exact or results)[:MAX_CANDIDATES]
        if chooser and len(exact) != 1 and pool:
            rules = client.rule_choice(exact, year, prefers_recent(s))
            try:
                chosen = chooser.choose(
                    s, [client.describe(r) for r in pool], rules["id"] if rules else None
                )
            except ChooserUnavailable:
                return client.pick(exact, year, prefers_recent(s)), False
            return (client.details(chosen) if chosen else Match(tmdb_id=None)), True
        return client.pick(exact, year, prefers_recent(s)), True

    def by_override(tmdb_id: int) -> tuple[Match, bool]:
        return client.details(tmdb_id), True

    def resolve(s: Showing) -> Match:
        if s.film_title in overrides:
            tmdb_id = overrides[s.film_title]
            if tmdb_id is None:
                return Match(tmdb_id=None)  # deliberate: not a miss, not logged
            key = f"tmdb:{tmdb_id}"
            fetch = partial(by_override, tmdb_id)
        else:
            key = lookup_key(s)
            fetch = partial(look_up, s)
        if key not in matches:
            if (match := cache.get(key)) is None:
                match, final = fetch()
                if final:
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


def load_env(name: str, env_path: Path = ENV_PATH) -> str | None:
    """name from the environment, else from .env; None if unset."""
    if value := os.environ.get(name):
        return value
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            key, _, value = line.partition("=")
            if key.strip() == name and value.strip():
                return value.strip()
    return None


def load_token(env_path: Path = ENV_PATH) -> str:
    if token := load_env("TMDB_API_KEY", env_path):
        return token
    raise SystemExit("TMDB_API_KEY not set (environment or .env)")


def report(chooser: ClaudeChooser | None) -> None:
    if chooser and chooser.calls:
        log.info(
            "Claude asked about %d films: %d matched, %d none",
            chooser.calls,
            chooser.answers["matched"],
            chooser.answers["none"],
        )


if __name__ == "__main__":
    from scrapers import ritz

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    chooser = claude_chooser()
    results = enrich(ritz.fetch(), TMDBClient(load_token()), Cache(), load_overrides(), chooser)
    report(chooser)
    seen = set()
    for s in results:
        if s.film_title not in seen:
            seen.add(s.film_title)
            print(f"{s.film_title!r:60} {s.tmdb_id} {s.year} {s.director} {s.rating}")
    matched = sum(s.tmdb_id is not None for s in results)
    print(f"{matched}/{len(results)} showings matched, {len(seen)} films")
