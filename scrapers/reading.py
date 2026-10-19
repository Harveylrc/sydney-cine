"""Reading Cinemas (Rhodes, Auburn, Rouse Hill): a JSON API, Australia only.

DECISIONS (venue table, 2026-10-19): GET prod-api.readingcinemas.com.au/settings/1
(no auth) gives data.settings.token, a bearer token that expires the same day;
GET /films?countryId=1&cinemaId=<id>&status=nowShowing&flag= with that token as
the Authorization header gives data[]: films (name, director, length,
release_date, synopsis) with showdates[] -> showtypes[] (type: Standard,
TitanLuxe…) -> showtimes[] (id, ScheduledFilmId "HO000…", date_time with its
+11:00 offset, soldout). The API host has no robots.txt; readingcinemas.com.au
allows everything. The token is never saved or logged.

The API refuses requests from outside Australia, so the nightly job (US) can't
reach it. `make reading-refresh`, run over an Australian connection, fetches it
live and commits a trimmed copy, cache/reading-latest.json; when the live fetch
fails, fetch() uses that copy if it is under MAX_AGE old, else returns nothing.

Titles: a series prefix is cut and typed ("Reading Rewind - Taxi Driver (1976)"
-> retrospective "Taxi Driver (1976)"; "Tributes Night - …" -> special), and
"(Directors Cut 1979)" becomes the tag "Director's Cut" plus the year. Other
" - " in titles are real ("Paw Patrol - The Dino Movie") and kept. `caption` is
1 on every session, so it says nothing about open captions and isn't shown.
Sessions link to the cinema's page on readingcinemas.com.au: the site is an
app whose film pages can't be confirmed without guessing, and booking happens
on Vista, which we don't fetch.
"""

import json
import logging
import re
import sys
from datetime import datetime, timedelta
from html import unescape
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from models import SYDNEY_TZ, Showing
from scrapers import BaseScraper, is_non_film

log = logging.getLogger("reading")

API = "https://prod-api.readingcinemas.com.au"
SITE = "https://readingcinemas.com.au"
# Our venue slug suffix -> (Reading's cinemaId, name). Rouse Hill's id is
# "Rousehill" exactly (from /getcinemas); "rouse-hill" makes the API fail.
CINEMAS = {
    "rhodes": ("rhodes", "Rhodes"),
    "auburn": ("auburn", "Auburn"),
    "rouse-hill": ("Rousehill", "Rouse Hill"),
}
LATEST = Path(__file__).resolve().parent.parent / "cache" / "reading-latest.json"
MAX_AGE = timedelta(days=8)
SERIES = {  # title prefix -> (film type, tag)
    "Reading Rewind - ": ("retrospective", "Reading Rewind"),
    "Tributes Night - ": ("special", "Tributes Night"),
}
DIRECTORS_CUT = re.compile(r"\s*\(Director'?s Cut,?\s*(\d{4})\)", re.IGNORECASE)
TAGS = {"Standard": None, "TitanLuxe": "TitanLuxe"}  # showtype -> tag; others kept as written
FILM_KEYS = ("name", "director", "length", "synopsis", "release_date")
SHOWTIME_KEYS = ("id", "ScheduledFilmId", "date_time")

SYDNEY = ZoneInfo(SYDNEY_TZ)


def venue_slug(cinema: str) -> str:
    return f"reading-{cinema}"


def trim(films: list[dict]) -> list[dict]:
    """Only the fields we read, so the committed copy stays small."""
    return [
        {
            **{k: film.get(k) for k in FILM_KEYS},
            "showdates": [
                {
                    "showtypes": [
                        {
                            "type": showtype.get("type"),
                            "showtimes": [
                                {k: t.get(k) for k in SHOWTIME_KEYS}
                                for t in showtype.get("showtimes") or []
                                if t.get("enabled", True)
                            ],
                        }
                        for showtype in day.get("showtypes") or []
                    ]
                }
                for day in film.get("showdates") or []
            ],
        }
        for film in films
    ]


def clean_title(name: str) -> tuple[str, str | None, list[str]]:
    """(title, film type, tags)."""
    title, film_type, tags = unescape(name).strip(), None, []
    for prefix, (kind, tag) in SERIES.items():
        if title.startswith(prefix):
            title, film_type, tags = title[len(prefix) :], kind, [tag]
    if cut := DIRECTORS_CUT.search(title):
        title = DIRECTORS_CUT.sub(f" ({cut.group(1)})", title)
        tags.append("Director's Cut")
    return title.strip(), film_type, tags


def parse(payload: dict) -> list[Showing]:
    """payload: {"fetched": ISO time, "cinemas": {cinema id: trimmed films}}."""
    showings = []
    for cinema, films in payload["cinemas"].items():
        for film in films:
            title, film_type, tags = clean_title(film["name"])
            if is_non_film(title):
                continue
            synopsis = re.sub(r"<[^>]+>", " ", unescape(film.get("synopsis") or "")).strip()
            for day in film["showdates"]:
                for showtype in day["showtypes"]:
                    tag = TAGS.get(showtype["type"], showtype["type"])
                    for time in showtype["showtimes"]:
                        showings.append(
                            Showing(
                                venue_slug=venue_slug(cinema),
                                venue_name=f"Reading {CINEMAS[cinema][1]}",
                                film_title=title,
                                start=datetime.fromisoformat(time["date_time"]).astimezone(SYDNEY),
                                session_id=str(time["id"]),
                                booking_url=f"{SITE}/{CINEMAS[cinema][0].lower()}",
                                attributes=tags + ([tag] if tag else []),
                                film_type=film_type,
                                vista_movie_id=time.get("ScheduledFilmId"),
                                venue_synopsis=" ".join(synopsis.split()) or None,
                                runtime_min=int(film["length"]) if film.get("length") else None,
                                venue_director=film.get("director") or None,
                            )
                        )
    return showings


class ReadingScraper(BaseScraper):
    def fetch_live(self) -> dict:
        token = self.get(f"{API}/settings/1").json()["data"]["settings"]["token"]
        cinemas = {}
        for cinema, (cinema_id, _) in CINEMAS.items():
            response = self.get(
                f"{API}/films",
                params={"countryId": 1, "cinemaId": cinema_id, "status": "nowShowing", "flag": ""},
                headers={"Authorization": token},
            )
            cinemas[cinema] = trim(response.json()["data"])
        return {"fetched": datetime.now(SYDNEY).isoformat(timespec="seconds"), "cinemas": cinemas}

    def _save(self, host: str, url: str, body: bytes) -> None:
        if "/settings/" not in url:  # the settings response holds the token: never on disk
            super()._save(host, url, body)


def load_latest(path: Path = LATEST, now: datetime | None = None) -> dict | None:
    """The committed copy, if there is one under MAX_AGE old."""
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    age = (now or datetime.now(SYDNEY)) - datetime.fromisoformat(payload["fetched"])
    if age > MAX_AGE:
        log.warning("Reading: saved copy is %d days old; showing nothing", age.days)
        return None
    log.info("Reading: using the copy saved %s", payload["fetched"])
    return payload


def save_latest(payload: dict, path: Path = LATEST) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def fetch() -> list[Showing]:
    try:
        payload = ReadingScraper().fetch_live()
    except (requests.RequestException, KeyError, ValueError) as error:
        log.info("Reading: live API unavailable (%s); it answers Australian addresses only", error)
        payload = load_latest()
        return parse(payload) if payload else []
    save_latest(payload)
    return parse(payload)


def refresh() -> int:
    """make reading-refresh: fetch live (needs an Australian connection) and save."""
    try:
        payload = ReadingScraper().fetch_live()
    except requests.RequestException as error:
        print(f"Couldn't reach the Reading API ({error}). Is the Australian VPN on?")
        return 1
    save_latest(payload)
    showings = parse(payload)
    for cinema in CINEMAS:
        count = sum(s.venue_slug == venue_slug(cinema) for s in showings)
        print(f"Reading {CINEMAS[cinema][1]}: {count} sessions")
    print(f"Saved {LATEST.relative_to(LATEST.parent.parent)}")
    return 0 if all(any(s.venue_slug == venue_slug(c) for s in showings) for c in CINEMAS) else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if "--refresh" in sys.argv:
        sys.exit(refresh())
    results = fetch()
    print(f"{len(results)} showings, {len({s.film_title for s in results})} films")
