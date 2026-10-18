"""Hayden Orpheum: open JSON API at /api/movie/playing-now (robots.txt allows all).

One GET returns every film (Vista "reference", title, synopsisShort, duration)
with its sessionTimes: local date "2026-10-19", time "3:30pm", attributes
({shortName, description}) and a bookingLink on web.orpheum.com.au, which is
linked to, never fetched. The Orpheum has no genre labels, so film_type comes
from words in the title (DECISIONS.md precedence: festival > retro > event).
"""

import logging
import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from models import SYDNEY_TZ, Showing
from scrapers import BaseScraper

log = logging.getLogger("orpheum")

API = "https://www.orpheum.com.au/api/movie/playing-now"
VENUE_SLUG = "orpheum"
VENUE_NAME = "Hayden Orpheum"
# Session attribute shortName -> label shown; None drops it. Unlisted ones keep
# their description and are logged.
ATTRIBUTE_LABELS = {
    "70mm": "70mm",
    "3D": "3D",
    "AD": "Audio Description",
    "CCAP": "Closed Captions",
    "HI": None,  # same sessions as Closed Captions
    "NFT": "NFT",  # No Free Tickets: kept, per DECISIONS 2026-10-15
    "Sub": "Subtitled",
}
FESTIVAL = re.compile(r"\bFilm Festival\b|^[A-Z]{1,4}FF \d{4}\s+[-–]")  # "JFF 2026 - Pitfall"
RETRO = re.compile(r"\bRetro\b", re.IGNORECASE)
EVENT = re.compile(
    r"\b(?:Q&A|Live|Special Event|Preview Event|Sing-A-Long|Concert|Met Opera"
    r"|National Theatre|Exhibition on Screen|Jazz Lounge|Comedy)\b",
    re.IGNORECASE,
)
# A session listed under day D that starts before this belongs to D+1 (DECISIONS.md).
DAY_ROLLOVER = time(5, 0)
SESSION_KEY = re.compile(r"/showtimes/([^/]+)/")

SYDNEY = ZoneInfo(SYDNEY_TZ)


def film_type(title: str) -> str | None:
    if FESTIVAL.search(title):
        return "festival"
    if RETRO.search(title):
        return "retrospective"
    if EVENT.search(title):
        return "special"
    return None


def start_time(day: str, clock: str) -> datetime:
    """('2026-10-19', '3:30pm') -> 15:30 Sydney; before 05:00 rolls to the next day."""
    listed = date.fromisoformat(day)
    at = datetime.strptime(clock.strip().lower(), "%I:%M%p").time()
    if at < DAY_ROLLOVER:
        listed += timedelta(days=1)
    return datetime.combine(listed, at, tzinfo=SYDNEY)


def attributes(session: dict, unknown: set[str] | None = None) -> list[str]:
    labels = []
    for attribute in session["attributes"]:
        code = attribute["shortName"]
        if code in ATTRIBUTE_LABELS:
            label = ATTRIBUTE_LABELS[code]
        else:
            label = attribute.get("description") or code
            if unknown is not None:
                unknown.add(code)
        if label and label not in labels:
            labels.append(label)
    return labels


def plain_text(html: str | None) -> str | None:
    text = " ".join(BeautifulSoup(html or "", "html.parser").get_text(" ").split())
    return text or None


def minutes(duration) -> int | None:
    found = re.match(r"\s*(\d+)", str(duration or ""))
    return int(found.group(1)) or None if found else None


def parse_films(films: list[dict], unknown: set[str] | None = None) -> list[Showing]:
    showings = []
    for film in films:
        title = film["title"].strip()
        for session in film["sessionTimes"]:
            key = SESSION_KEY.search(session["bookingLink"])
            showings.append(
                Showing(
                    venue_slug=VENUE_SLUG,
                    venue_name=VENUE_NAME,
                    film_title=title,
                    start=start_time(session["date"], session["time"]),
                    session_id=key.group(1) if key else None,
                    booking_url=session["bookingLink"],
                    attributes=attributes(session, unknown),
                    film_type=film_type(title),
                    vista_movie_id=film.get("reference") or None,
                    venue_synopsis=plain_text(film.get("synopsisShort")),
                    runtime_min=minutes(film.get("duration")),
                )
            )
    return showings


class OrpheumScraper(BaseScraper):
    def fetch(self) -> list[Showing]:
        unknown = set()
        showings = parse_films(self.get(API).json(), unknown)
        if unknown:
            log.info("Orpheum attributes shown as described: %s", ", ".join(sorted(unknown)))
        return showings


def fetch() -> list[Showing]:
    return OrpheumScraper().fetch()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    results = fetch()
    for s in results[:30]:
        print(s.start.strftime("%a %d %b %H:%M"), s.film_title, s.film_type, s.attributes)
    print(f"{len(results)} showings, {len({s.film_title for s in results})} films")
