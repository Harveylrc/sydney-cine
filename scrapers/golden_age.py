"""Golden Age Cinema and Bar (Surry Hills): server-rendered /films/now-showing.

The page is grouped by day heading ("Sunday 18th October", no year). Under each
heading, one Thumb per session: title, subtitle "Dir. Miloš Forman | 81mins",
time "Sun 18 11:00 am" and a link to /film/{slug}. Notices such as "Closed for
a Private Event" are Thumbs too, but link elsewhere (/venue-hire) and are
skipped. The year comes from month rollover (scrapers.heading_dates). Class names carry a
build hash ("Thumb-module-scss-module__OGaEla__title"), so they are matched on
their stable suffix. robots.txt allows everything. Links go to the film page,
where tickets are sold; no session ids are published.
"""

import logging
import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag

from models import SYDNEY_TZ, Showing
from scrapers import BaseScraper, heading_dates, is_non_film

log = logging.getLogger("golden_age")

SITE = "https://www.ourgoldenage.com.au"
PAGE = f"{SITE}/films/now-showing"
VENUE_SLUG = "golden-age"
VENUE_NAME = "Golden Age"
CLOCK = re.compile(r"(\d{1,2}):(\d{2})\s*(am|pm)", re.IGNORECASE)
SUBTITLE = re.compile(r"Dir\.\s*(?P<director>.+?)\s*(?:\|\s*(?P<minutes>\d+)\s*mins?)?$")
# A session listed under day D that starts before this belongs to D+1 (DECISIONS.md).
DAY_ROLLOVER = time(5, 0)

SYDNEY = ZoneInfo(SYDNEY_TZ)


def has_class(suffix: str):
    """Match a CSS-module class by its stable suffix, e.g. '__title'."""
    return lambda classes: classes is not None and any(c.endswith(suffix) for c in classes.split())


def clock(text: str) -> time | None:
    found = CLOCK.search(text)
    if not found:
        return None
    hour = int(found.group(1)) % 12 + (12 if found.group(3).lower() == "pm" else 0)
    return time(hour, int(found.group(2)))


def credits(subtitle: str) -> tuple[str | None, int | None]:
    """'Dir. Miloš Forman | 81mins' -> ('Miloš Forman', 81)."""
    found = SUBTITLE.match(subtitle.strip())
    if not found:
        return None, None
    minutes = found.group("minutes")
    director = found.group("director").strip()
    if not any(ch.isalpha() for ch in director):
        director = ""  # "Dir. ???" for a mystery screening
    return director or None, int(minutes) if minutes else None


def text_of(thumb: Tag, suffix: str) -> str:
    node = thumb.find(class_=has_class(suffix))
    return node.get_text(" ", strip=True) if node else ""


def parse_page(html: str, today: date) -> list[Showing]:
    soup = BeautifulSoup(html, "html.parser")
    headings = soup.find_all(class_=has_class("__group__heading"))
    showings = []
    for heading, day in zip(
        headings,
        heading_dates([h.get_text(" ", strip=True) for h in headings], today),
        strict=True,
    ):
        if day is None:
            continue
        for thumb in heading.parent.find_all("div", class_=has_class("__Thumb")):
            link = thumb.find("a", href=True)
            if not link or not link["href"].startswith("/film/"):
                continue  # "Closed for a Private Event" and other notices
            if is_non_film(text_of(thumb, "__title")):
                continue  # "Film Trivia"
            at = clock(text_of(thumb, "__eventDate"))
            if at is None:
                log.warning("Golden Age session without a time: %r", text_of(thumb, "__title"))
                continue
            start_day = day + timedelta(days=1) if at < DAY_ROLLOVER else day
            director, runtime = credits(text_of(thumb, "__subtitle"))
            showings.append(
                Showing(
                    venue_slug=VENUE_SLUG,
                    venue_name=VENUE_NAME,
                    film_title=text_of(thumb, "__title"),
                    start=datetime.combine(start_day, at, tzinfo=SYDNEY),
                    booking_url=SITE + link["href"],
                    venue_director=director,
                    runtime_min=runtime,
                )
            )
    return showings


class GoldenAgeScraper(BaseScraper):
    def fetch(self) -> list[Showing]:
        today = datetime.now(SYDNEY).date()
        return parse_page(self.get(PAGE).text, today)


def fetch() -> list[Showing]:
    return GoldenAgeScraper().fetch()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    results = fetch()
    for s in results:
        print(s.start.strftime("%a %d %b %Y %H:%M"), s.film_title, s.venue_director, s.runtime_min)
    print(f"{len(results)} showings, {len({s.film_title for s in results})} films")
