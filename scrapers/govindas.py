"""Govinda's Movie Room (Darlinghurst): one server-rendered page, /movies.

div.movieDay per day: an h2 "Thursday, October 22" (no year: scrapers.heading_dates
after reordering), then ul.movieList with one li per session: a link
/movie/<film id>/<slug>?t=<session id> holding an h3 title and the time
("6:30 pm"), and a backdrop image named after the film and usually its year
("/persistent/images/backdrop/Barry-Lyndon-…-1975.jpg").

Titles carry promotion, which is cut: a classification and everything after it
("The Road to Patagonia (M) Five Stars.. …"), "BOOKINGS ESSENTIAL MOVIE ONLY
RESTAURANT CLOSED" (kept as the tag "Movie only": Govinda's usually sells dinner
and a film together) and trailing capitalised slogans ("… THE MOST BEAUTIFUL
FILM EVER MADE"). What remains unusual is mapped in tmdb_overrides.csv.

robots.txt has no rules (Cloudflare content-signal comments only, no signals
set). Session links are linked, never fetched. Checked 2026-10-19.
"""

import logging
import re
from datetime import datetime, time, timedelta
from urllib.parse import parse_qs, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from models import SYDNEY_TZ, Showing
from scrapers import BaseScraper, heading_dates

log = logging.getLogger("govindas")

SITE = "https://www.govindas.com.au"
PAGE = f"{SITE}/movies"
VENUE_SLUG = "govindas"
VENUE_NAME = "Govinda's Movie Room"
CLOCK = re.compile(r"(\d{1,2}):(\d{2})\s*(am|pm)", re.IGNORECASE)
DAY = re.compile(r"(\w+day),?\s+(\w+)\s+(\d{1,2})", re.IGNORECASE)  # Thursday, October 22
MOVIE_ONLY = re.compile(
    r"\s*BOOKINGS ESSENTIAL\s+MOVIE ONLY\s+RESTAURANT CLOSED\s*(?:\(\d{4}\))?", re.IGNORECASE
)
RATING_AND_AFTER = re.compile(r"\s*\((?:G|PG|M|MA ?15\+|R ?18\+|CTC)\).*$")
SLOGAN = re.compile(r"(?:\s+[A-Z][A-Z'’.,!-]+){3,}.*$")  # three or more words in capitals
BACKDROP_YEAR = re.compile(r"-((?:18|19|20)\d\d)\.jpg$")
DAY_ROLLOVER = time(5, 0)  # a session before 05:00 belongs to the next day (DECISIONS)

SYDNEY = ZoneInfo(SYDNEY_TZ)


def clean_title(raw: str) -> tuple[str, list[str]]:
    """(title, tags) from a listed title."""
    tags = ["Movie only"] if MOVIE_ONLY.search(raw) else []
    title = MOVIE_ONLY.sub("", raw)
    title = RATING_AND_AFTER.sub("", title)
    title = SLOGAN.sub("", title)
    return re.sub(r"\s+", " ", title).strip(), tags


def clock(text: str) -> time | None:
    found = CLOCK.search(text)
    if not found:
        return None
    hour = int(found.group(1)) % 12 + (12 if found.group(3).lower() == "pm" else 0)
    return time(hour, int(found.group(2)))


def parse_page(html: str, today) -> list[Showing]:
    soup = BeautifulSoup(html, "html.parser")
    days = soup.select("div.movieDay")
    headings = []
    for day in days:
        text = day.find("h2").get_text(" ", strip=True)
        found = DAY.search(text)
        # heading_dates reads "Thursday 22 October"
        headings.append(f"{found.group(1)} {found.group(3)} {found.group(2)}" if found else text)
    showings = []
    for day, on in zip(days, heading_dates(headings, today), strict=True):
        for item in day.select("ul.movieList > li"):
            link = item.find("a")
            start = clock(link.get_text(" ", strip=True))
            if on is None or start is None:
                log.warning("Session not understood: %r", link.get_text(" ", strip=True)[:80])
                continue
            title, tags = clean_title(link.find("h3").get_text(" ", strip=True))
            backdrops = [
                i.get("data-src", "")
                for i in item.find_all("img")
                if "backdrop" in i.get("data-src", "")
            ]
            year = BACKDROP_YEAR.search(backdrops[0]) if backdrops else None
            if year and not re.search(r"\(\d{4}\)$", title):
                title = f"{title} ({year.group(1)})"  # enrich reads it as the year to match
            when = datetime.combine(on, start, tzinfo=SYDNEY)
            if start < DAY_ROLLOVER:
                when += timedelta(days=1)
            url = urljoin(SITE, link["href"])
            showings.append(
                Showing(
                    venue_slug=VENUE_SLUG,
                    venue_name=VENUE_NAME,
                    film_title=title,
                    start=when,
                    session_id=parse_qs(urlsplit(url).query).get("t", [None])[0],
                    booking_url=url,
                    attributes=tags,
                )
            )
    return showings


class GovindasScraper(BaseScraper):
    def fetch(self) -> list[Showing]:
        return parse_page(self.get(PAGE).text, datetime.now(SYDNEY).date())


def fetch() -> list[Showing]:
    return GovindasScraper().fetch()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    results = fetch()
    for s in results:
        print(s.start.strftime("%a %d %b %Y %H:%M"), s.film_title, s.attributes, s.session_id)
    print(f"{len(results)} showings, {len({s.film_title for s in results})} films")
