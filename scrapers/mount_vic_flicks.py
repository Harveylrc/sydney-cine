"""Mount Vic Flicks (Mount Victoria, Blue Mountains): one server-rendered page.

/sessions/ lists every published session under ul.session-times-list: an h2 per
day with the year ("Wednesday, 21 October 2026"), then for each film an h3
("Sense and Sensibility (PG)", sometimes "Wicker - Advance Screening (MA 15+)")
followed by div.times, one a.time per session ("6:00 pm", or "6:30 pm (Tickets
$20/15 +BF)" for events). Session links go to /sessions/<film>/<id>/ or, for
events, TryBooking: we link to them and never fetch them. The <li> tags aren't
closed, so the page is read as a flat run of h2 / h3 / div.times.

No robots.txt (404), so nothing is disallowed. Checked 2026-10-19.
"""

import logging
import re
from datetime import datetime, time, timedelta
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from models import SYDNEY_TZ, Showing
from scrapers import MONTHS, BaseScraper, is_non_film

log = logging.getLogger("mount_vic_flicks")

SITE = "https://mountvicflicks.com.au"
PAGE = f"{SITE}/sessions/"
VENUE_SLUG = "mount-vic-flicks"
VENUE_NAME = "Mount Vic Flicks"
DAY = re.compile(r"(\d{1,2})\s+(\w+)\s+(\d{4})")
CLOCK = re.compile(r"(\d{1,2}):(\d{2})\s*(am|pm)", re.IGNORECASE)
RATING = re.compile(r"\s*\((?:G|PG|M|MA ?15\+|R ?18\+|CTC|Exempt|E)\)\s*$", re.IGNORECASE)
# " - Advance Screening", " - Halloween Special", " - One screening only!": how the
# film is presented, not its title. Becomes a tag and, where clear, the film type.
PRESENTED = re.compile(
    r"\s+[-–]\s+(?P<note>[^-–]*\b(?:Screening|Special|only|Anniversary|Preview|Q&A)\b[^-–]*)$",
    re.IGNORECASE,
)
DAY_ROLLOVER = time(5, 0)  # a session before 05:00 belongs to the next day (DECISIONS)

SYDNEY = ZoneInfo(SYDNEY_TZ)


def clock(text: str) -> time | None:
    found = CLOCK.search(text)
    if not found:
        return None
    hour = int(found.group(1)) % 12 + (12 if found.group(3).lower() == "pm" else 0)
    return time(hour, int(found.group(2)))


def film_type(note: str | None) -> str | None:
    note = (note or "").lower()
    if "advance" in note or "preview" in note:
        return "new_release"
    if "special" in note or "only" in note:
        return "special"
    if "anniversary" in note:
        return "retrospective"
    return None


def parse_page(html: str) -> list[Showing]:
    soup = BeautifulSoup(html, "html.parser")
    listing = soup.find("ul", class_="session-times-list")
    if not listing:
        log.warning("No session list on %s", PAGE)
        return []
    showings, day, title, note = [], None, None, None
    for node in listing.find_all(["h2", "h3", "div"]):
        if node.name == "h2":
            found = DAY.search(node.get_text(" ", strip=True))
            month = MONTHS.get(found.group(2).lower()) if found else None
            day = (
                datetime(int(found.group(3)), month, int(found.group(1))).date() if month else None
            )
            if day is None:
                log.warning("Day heading not understood: %r", node.get_text(strip=True))
        elif node.name == "h3":
            title = RATING.sub("", node.find("a").get_text(" ", strip=True))
            presented = PRESENTED.search(title)
            note = presented.group("note").strip().rstrip("!") if presented else None
            title = PRESENTED.sub("", title)
        elif "times" in (node.get("class") or []):
            for link in node.find_all("a", class_="time"):
                start = clock(link.get_text(" ", strip=True))
                if day is None or start is None or title is None:
                    log.warning("Session not understood: %r", link.get_text(strip=True))
                    continue
                when = datetime.combine(day, start, tzinfo=SYDNEY)
                if start < DAY_ROLLOVER:
                    when += timedelta(days=1)
                url = urljoin(SITE, link["href"])
                own_page = url.startswith(f"{SITE}/sessions/")
                showings.append(
                    Showing(
                        venue_slug=VENUE_SLUG,
                        venue_name=VENUE_NAME,
                        film_title=title,
                        start=when,
                        session_id=url.rstrip("/").rsplit("/", 1)[-1] if own_page else None,
                        booking_url=url,
                        attributes=[note] if note else [],
                        film_type=film_type(note),
                    )
                )
    return showings


class MountVicFlicksScraper(BaseScraper):
    def fetch(self) -> list[Showing]:
        return [s for s in parse_page(self.get(PAGE).text) if not is_non_film(s.film_title)]


def fetch() -> list[Showing]:
    return MountVicFlicksScraper().fetch()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    results = fetch()
    for s in results:
        print(
            s.start.strftime("%a %d %b %Y %H:%M"),
            s.film_title,
            s.attributes,
            s.film_type,
            s.booking_url,
        )
    print(f"{len(results)} showings, {len({s.film_title for s in results})} films")
