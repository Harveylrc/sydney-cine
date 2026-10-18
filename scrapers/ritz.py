"""Ritz Randwick: server-rendered listing pages at /now-showing/YYYY-MM-DD.

Each film is a div.Movie with a span.Title and one a.sessions-link per session.
A link carries the session id (?s=), the time ("1:00 pm") and zero or more
span.Attribute tags, some comma-joined ("NFT, Q&A"). Its data-genre lists genres
plus "New Release", "Retrospective" or "Film Festival". film_type comes from
these and the tags, in the precedence set in DECISIONS.md. Ticket links are
only linked to, never fetched.
"""

from datetime import date, datetime, time, timedelta
from urllib.parse import parse_qs, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from models import SYDNEY_TZ, Showing
from scrapers import BaseScraper, is_non_film

BASE_URL = "https://www.ritzcinemas.com.au"
VENUE_SLUG = "ritz-randwick"
VENUE_NAME = "Ritz Randwick"
DAYS_AHEAD = 14
# Availability notices, not properties of the session (DECISIONS.md).
TRANSIENT_TAGS = {"selling fast", "sold out", "last chance"}
# film_type precedence (DECISIONS.md): festival tag > data-genre label > other tags.
FESTIVAL_TAGS = {"jiff", "sff"}
GENRE_FILM_TYPES = {
    "Film Festival": "festival",
    "Retrospective": "retrospective",
    "New Release": "new_release",
}
TAG_FILM_TYPES = {
    "retro": "retrospective",
    "specevent": "special",
    "livemusic": "special",
    "stage": "special",
    "theatre": "special",
}
# Sessions listed under day D that start before this belong to D+1 (DECISIONS.md).
DAY_ROLLOVER = time(5, 0)

SYDNEY = ZoneInfo(SYDNEY_TZ)


def parse_day(html: str, day: date) -> list[Showing]:
    soup = BeautifulSoup(html, "html.parser")
    showings = []
    for movie in soup.select("div.Movie"):
        title = movie.select_one(".Title").get_text(strip=True)
        if is_non_film(title):
            continue
        for link in movie.select("a.sessions-link"):
            clock = datetime.strptime(
                link.select_one("span.Time").get_text(strip=True), "%I:%M %p"
            ).time()
            start_day = day + timedelta(days=1) if clock < DAY_ROLLOVER else day
            attributes = [
                tag.strip()
                for span in link.select("span.Attribute")
                for tag in span.get_text(strip=True).split(",")
                if tag.strip() and tag.strip().lower() not in TRANSIENT_TAGS
            ]
            showings.append(
                Showing(
                    venue_slug=VENUE_SLUG,
                    venue_name=VENUE_NAME,
                    film_title=title,
                    start=datetime.combine(start_day, clock, tzinfo=SYDNEY),
                    session_id=parse_qs(urlsplit(link["href"]).query)["s"][0],
                    booking_url=urljoin(BASE_URL, link["href"]),
                    attributes=attributes,
                    film_type=film_type(link.get("data-genre", ""), attributes),
                )
            )
    return showings


def film_type(data_genre: str, tags: list[str]) -> str | None:
    tags = [tag.lower() for tag in tags]
    if any(tag in FESTIVAL_TAGS for tag in tags):
        return "festival"
    genres = {genre.strip() for genre in data_genre.split(",")}
    for label, kind in GENRE_FILM_TYPES.items():
        if label in genres:
            return kind
    for tag, kind in TAG_FILM_TYPES.items():
        if tag in tags:
            return kind
    return None


class RitzScraper(BaseScraper):
    def fetch(self) -> list[Showing]:
        today = datetime.now(SYDNEY).date()
        showings = []
        for offset in range(DAYS_AHEAD):
            day = today + timedelta(days=offset)
            response = self.get(f"{BASE_URL}/now-showing/{day.isoformat()}")
            showings.extend(parse_day(response.text, day))
        return showings


def fetch() -> list[Showing]:
    return RitzScraper().fetch()


if __name__ == "__main__":
    results = fetch()
    for s in results:
        print(s.start.strftime("%a %d %b %H:%M"), s.film_title, s.attributes or "")
    print(f"{len(results)} showings")
