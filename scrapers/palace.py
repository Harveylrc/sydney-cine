"""Palace: the full schedule is embedded in each cinema page's __NEXT_DATA__ JSON.

GET /cinemas/{slug} for the three Sydney cinemas. props.pageProps.sessions is a
list of films (Vista movieId, title, genreNames), each with its sessions
(sessionId, date, sessionInfo strings, displayAttributeText). Session dates end
in "Z" but are Sydney wall-clock time: Palace's own site drops the "Z" and reads
them as local, and the hours only make sense that way (10:00-21:00). The page is
parsed rather than /_next/data/{buildId}/…, whose buildId changes on every
deploy (DECISIONS.md). Booking links point at buy.palacecinemas.com.au: linked
to, never fetched.
"""

import json
import logging
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from models import SYDNEY_TZ, Showing
from scrapers import BaseScraper, is_non_film

log = logging.getLogger("palace")

SITE = "https://www.palacecinemas.com.au"
BOOKING = "https://buy.palacecinemas.com.au/?cinema={cinema}&session={session}"
# Site slug -> (our venue slug, venue name)
CINEMAS = {
    "palace-central-sydney": ("palace-central", "Palace Central"),
    "palace-norton-street": ("palace-norton-street", "Palace Norton Street"),
    "palace-moore-park": ("palace-moore-park", "Palace Moore Park"),
}
# sessionInfo and displayAttributeText -> label shown; None drops it. Unlisted
# text is kept as Palace wrote it (it is already meant for display) and logged.
SESSION_LABELS = {
    "Audio Description Session": "Audio Description",
    "Closed Captioning Available": "Closed Captions",
    "Hearing Impaired": None,  # same sessions as Closed Captioning
    "No Free Tickets": "NFT",  # kept like every venue (DECISIONS 2026-10-18)
    "Special Event": "Special Event",
    "SPECIAL EVENT": "Special Event",
    "RETRO": "Retro",
    "RECLINER": None,  # seating
    "GOLDEN YEARS": "Golden Years",
    "Sneak": "Sneak Preview",
    "MOVIE CLUB": "Movie Club",
    "BABES IN ARMS": "Babes in Arms",
    "INCL. Q&A": "Q&A",
}
# film_type precedence (DECISIONS.md): festival > venue genre label > session tags.
FESTIVAL_PREFIX = re.compile(r"^[A-Z]{1,4}FF\d{2}\s")  # "BFF26 Hamlet"
GENRE_FILM_TYPES = {
    "Film Festival": "festival",
    "Retrospective": "retrospective",
    "Opera": "special",
    "Ballet": "special",
    "Theatre": "special",
    "Concert": "special",
    "Alternative Content": "special",
}
TAG_FILM_TYPES = {"Retro": "retrospective", "Special Event": "special"}

SYDNEY = ZoneInfo(SYDNEY_TZ)


def next_data(html: str) -> dict:
    script = BeautifulSoup(html, "html.parser").find("script", id="__NEXT_DATA__")
    return json.loads(script.string)


def start_time(vista_date: str) -> datetime:
    """'2026-10-19T12:30:00.000Z' -> 12:30 Sydney time (the 'Z' is not UTC)."""
    local = datetime.fromisoformat(vista_date.removesuffix("Z"))
    return local.replace(tzinfo=SYDNEY)


def attributes(session: dict, unknown: set[str] | None = None) -> list[str]:
    raw = [*session["sessionInfo"], session.get("displayAttributeText")]
    if session.get("isPlatinum"):
        raw.append("Platinum")
    labels = []
    for text in filter(None, raw):
        label = SESSION_LABELS.get(text, text)
        if text not in SESSION_LABELS and text != "Platinum" and unknown is not None:
            unknown.add(text)
        if label and label not in labels:
            labels.append(label)
    return labels


def film_type(movie: dict, labels: list[str]) -> str | None:
    if FESTIVAL_PREFIX.match(movie["title"]):
        return "festival"
    for genre in movie["genreNames"]:  # Palace order; festival first if present
        if genre == "Film Festival":
            return "festival"
    for genre in movie["genreNames"]:
        if genre in GENRE_FILM_TYPES:
            return GENRE_FILM_TYPES[genre]
    for label in labels:
        if label in TAG_FILM_TYPES:
            return TAG_FILM_TYPES[label]
    return None


def runtime(text: str | None) -> int | None:
    """'131 MIN' -> 131."""
    found = re.match(r"\s*(\d+)", text or "")
    return int(found.group(1)) if found else None


def parse_page(html: str, unknown: set[str] | None = None) -> list[Showing]:
    props = next_data(html)["props"]["pageProps"]
    venue_slug, venue_name = CINEMAS[props["cinema"]["slug"]]
    showings = []
    for movie in props["sessions"]:
        if is_non_film(movie["title"]):
            continue
        for session in movie["sessions"]:
            labels = attributes(session, unknown)
            start = start_time(session["date"])
            showings.append(
                Showing(
                    venue_slug=venue_slug,
                    venue_name=venue_name,
                    film_title=movie["title"].strip(),
                    start=start,
                    session_id=session["sessionId"],
                    booking_url=BOOKING.format(
                        cinema=session["cinemaId"], session=session["sessionId"]
                    ),
                    attributes=labels,
                    film_type=film_type(movie, labels),
                    vista_movie_id=movie["movieId"],
                    venue_synopsis=(movie.get("synopsis") or "").strip() or None,
                    runtime_min=runtime(movie.get("runTime")),
                )
            )
    return showings


class PalaceScraper(BaseScraper):
    def fetch(self) -> list[Showing]:
        showings, unknown = [], set()
        for slug in CINEMAS:
            showings.extend(parse_page(self.get(f"{SITE}/cinemas/{slug}").text, unknown))
        if unknown:
            log.info("Palace session labels kept as written: %s", ", ".join(sorted(unknown)))
        return showings


def fetch() -> list[Showing]:
    return PalaceScraper().fetch()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    results = fetch()
    for s in results[:30]:
        print(s.venue_name, s.start.strftime("%a %d %b %H:%M"), s.film_title, s.attributes)
    print(f"{len(results)} showings, {len({s.film_title for s in results})} films")
