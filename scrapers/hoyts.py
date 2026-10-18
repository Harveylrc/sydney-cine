"""Hoyts: open JSON API, no auth, at apim-aea.hoyts.com.au/cinemaapi-au-live/api/.

GET movies/ lists every film (Vista id "HO000…" and name); GET sessions/{cinemaId}
lists one cinema's sessions from now onwards, weeks ahead. A session has its Vista
movieId, a local "date" and a UTC "utcDate", the screen type, and short tag codes
("AD", "CC", "INFVIS"…). Only the Sydney cinemas in CINEMAS are fetched. Tag
codes are turned into readable attributes; seat and price codes are dropped.
Session "link"s are ticketing pages: linked to, never fetched.
"""

import logging
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from models import SYDNEY_TZ, Showing
from scrapers import BaseScraper

log = logging.getLogger("hoyts")

API = "https://apim-aea.hoyts.com.au/cinemaapi-au-live/api"
SITE = "https://www.hoyts.com.au"
# Greater Sydney Hoyts cinemas (cinemaId -> name). Other NSW sites (Newcastle,
# Maitland, Wollongong, Tweed, Central Coast) are left out; see DECISIONS.md.
CINEMAS = {
    "BANKTN": "Bankstown",
    "WESCIN": "Blacktown",
    "BROADW": "Broadway",
    "CHWOOD": "Chatswood Mandarin",
    "CWFFLD": "Chatswood Westfield",
    "CROCIN": "Cronulla",
    "EGDENS": "Eastgardens",
    "SHOWGR": "Entertainment Quarter",
    "MTDRTT": "Mt Druitt",
    "PENRTH": "Penrith",
    "WGHMAL": "Warringah Mall",
    "WETHER": "Wetherill Park",
}
# Session tag codes worth showing. Everything else is seating (RC, PRC, LUXA…),
# pricing (DISCOUNT) or a code we can't read yet; unknown codes are logged.
TAG_LABELS = {
    "AD": "Audio Description",
    "CC": "Closed Captions",
    "OC": "Open Captions",
    "SS": "Sensory Screening",
    "3D": "3D",
    "IMAX": "IMAX",
    "SCREENX": "ScreenX",
    "XTREME": "Xtremescreen",
    "LUX": "LUX",
    "APEX": "APEX",
    "DBOX": "D-BOX",
    "ONYX": "Onyx",
    "INFVIS": "Infinity Vision",
    "ATMOS": "Dolby Atmos",
    "SPECEVENT": "Special Event",
}
DROPPED_TAGS = {
    *("RC", "PRC", "Non RC", "LUXA", "LUXB", "LUXC", "MSLX", "DAYBEDS", "LOUNGES", "DBOX Rows"),
    *("DISCOUNT", "No Alcohol", "STANDARD"),
}
# film_type (DECISIONS.md precedence): festival strand > event/live > None.
FESTIVAL_PREFIX = re.compile(r"^\((?:LFF)\)", re.IGNORECASE)
SPECIAL_GENRES = {"Main Stage", "Concert"}
SPECIAL_TAGS = {"SPECEVENT"}

SYDNEY = ZoneInfo(SYDNEY_TZ)


def movie_index(movies: list[dict]) -> dict[str, dict]:
    """Vista id -> movie. One film can carry several ids: "HO00008129,HO00011223"."""
    return {vista_id.strip(): m for m in movies for vista_id in m["vistaId"].split(",")}


def start_time(session: dict) -> datetime:
    """utcDate converted to Sydney; the local "date" if utcDate is a placeholder."""
    utc = datetime.fromisoformat(session["utcDate"])
    if utc.year > 2000:
        return utc.astimezone(SYDNEY)
    return datetime.fromisoformat(session["date"]).replace(tzinfo=SYDNEY)


def attributes(session: dict, unknown: set[str] | None = None) -> list[str]:
    """Readable labels for the session's codes; unreadable codes go into unknown."""
    labels = []
    for code in [session["typeId"], *session["originalTags"]]:
        label = TAG_LABELS.get(code)
        if label is None:
            if code not in DROPPED_TAGS and unknown is not None:
                unknown.add(code)
        elif label not in labels:
            labels.append(label)
    return labels


def film_type(movie: dict, session: dict) -> str | None:
    if FESTIVAL_PREFIX.match(movie["name"]):
        return "festival"
    if SPECIAL_TAGS & set(session["originalTags"]) or SPECIAL_GENRES & set(movie["genres"]):
        return "special"
    return None


def parse_sessions(
    sessions: list[dict], movies: dict[str, dict], unknown: set[str] | None = None
) -> list[Showing]:
    showings = []
    for session in sessions:
        cinema = session["cinemaId"]
        movie = movies.get(session["movieId"])
        if cinema not in CINEMAS:
            continue
        if movie is None:
            log.warning("Hoyts session %s: unknown movie %s", session["id"], session["movieId"])
            continue
        showings.append(
            Showing(
                venue_slug=f"hoyts-{cinema_slug(cinema)}",
                venue_name=f"Hoyts {CINEMAS[cinema]}",
                film_title=movie["name"].strip(),
                start=start_time(session),
                session_id=str(session["id"]),
                booking_url=SITE + session["link"] if session.get("link") else None,
                attributes=attributes(session, unknown),
                film_type=film_type(movie, session),
                vista_movie_id=session["movieId"],
            )
        )
    return showings


def cinema_slug(cinema_id: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", CINEMAS[cinema_id].lower()).strip("-")


class HoytsScraper(BaseScraper):
    def fetch(self) -> list[Showing]:
        movies = movie_index(self.get(f"{API}/movies/").json())
        showings, unknown = [], set()
        for cinema in CINEMAS:
            sessions = self.get(f"{API}/sessions/{cinema}").json()
            showings.extend(parse_sessions(sessions, movies, unknown))
        if unknown:
            log.info("Hoyts tag codes not shown: %s", ", ".join(sorted(unknown)))
        return showings


def fetch() -> list[Showing]:
    return HoytsScraper().fetch()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    results = fetch()
    for s in results[:40]:
        print(s.venue_name, s.start.strftime("%a %d %b %H:%M"), s.film_title, s.attributes)
    print(f"{len(results)} showings, {len({s.film_title for s in results})} films")
