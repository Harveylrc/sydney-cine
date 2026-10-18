"""Glenbrook Cinema (Blue Mountains): server-rendered pages, one per film.

/movies/ lists every film as a "comingsoon" block: title, screening dates, labels
("20th Anniversary", "Live Play") and a button that reads "Info & Sessions" once
sessions are on sale, else just "Info". Only films with sessions are fetched.
Live plays (the Glenbrook Players) are skipped.

A film page (/movies/<slug>/) has the title (and sometimes " - 1996", the year),
"Running Time: 132 minutes", the synopsis, and a #sessions block: day headings
("Tuesday 20 October", no year: scrapers.heading_dates) each followed by one
"movie" block per session with its time ("2:00pm"), notes ("Open Captions
Session", "Special Event $25") and a "Book Now" link to
/online-booking/?session_id=N, which we link to and never fetch. Sessions more
than seven days out have no booking link yet; they link to the film page.
"One Night Only" events and "Special Event" sessions are typed special;
"Anniversary" re-releases retrospective.

/program/ is only a PDF of the printed programme. robots.txt disallows nothing
we use. Checked 2026-10-19.
"""

import logging
import re
from datetime import date, datetime, time, timedelta
from urllib.parse import parse_qs, urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag

from models import SYDNEY_TZ, Showing
from scrapers import BaseScraper, heading_dates, is_non_film

log = logging.getLogger("glenbrook")

SITE = "https://www.glenbrookcinema.com.au"
MOVIES = f"{SITE}/movies/"
VENUE_SLUG = "glenbrook-cinema"
VENUE_NAME = "Glenbrook Cinema"
CLOCK = re.compile(r"(\d{1,2}):(\d{2})\s*(am|pm)", re.IGNORECASE)
TITLE_YEAR = re.compile(r"\s*-\s*(\d{4})$")
RUNTIME = re.compile(r"(\d+)\s*minutes", re.IGNORECASE)
PRICE = re.compile(r"\s*\$\d+(?:\.\d\d)?")
# Session notes -> tag shown; None drops the note. Unlisted notes are kept as written.
NOTES = {
    "open captions session": "Open Captions",
    "special event": None,  # becomes the film type instead
    "event tickets": None,  # pricing ("Event Tickets $30")
}
DAY_ROLLOVER = time(5, 0)  # a session before 05:00 belongs to the next day (DECISIONS)

SYDNEY = ZoneInfo(SYDNEY_TZ)


def film_links(html: str) -> list[tuple[str, str]]:
    """(url, labels) for each film on /movies/ whose sessions are on sale."""
    soup = BeautifulSoup(html, "html.parser")
    films = []
    for block in soup.find_all("div", class_="comingsoon"):
        button = block.find("a", class_="sessions")
        if not button or "Sessions" not in button.get_text():
            continue
        labels = block.find("div", class_="movie").get_text(" ", strip=True)
        if "Live Play" in labels:
            log.info("Skipped a live play: %s", button["href"])
            continue
        films.append((urljoin(SITE, button["href"]), labels))
    return films


def clock(text: str) -> time | None:
    found = CLOCK.search(text)
    if not found:
        return None
    hour = int(found.group(1)) % 12 + (12 if found.group(3).lower() == "pm" else 0)
    return time(hour, int(found.group(2)))


def own_text(tag: Tag) -> str:
    """The tag's text without its child tags' (a title without its "(PG)")."""
    return " ".join(s.strip() for s in tag.find_all(string=True, recursive=False)).strip()


def parse_film(html: str, today: date, labels: str = "", url: str | None = None) -> list[Showing]:
    """Sessions on a film page; url is the page's, the link for sessions not yet
    bookable (bookings open seven days ahead)."""
    soup = BeautifulSoup(html, "html.parser")
    box = soup.find("article", class_="movies-box")
    heading = box.find("h1").get_text(" ", strip=True)
    year = TITLE_YEAR.search(heading)
    page_title = TITLE_YEAR.sub("", heading)
    if year:  # "(1996)": enrich reads it as the year to match
        page_title = f"{page_title} ({year.group(1)})"
    runtime = box.find("div", class_="runningtime")
    minutes = RUNTIME.search(runtime.get_text()) if runtime else None
    synopsis = box.find("div", class_="movies-full")
    retrospective = "Anniversary" in labels
    one_off = "One Night Only" in labels

    sessions = box.find(id="sessions")
    if not sessions:
        return []
    blocks = sessions.find_all("div", class_=["date", "movie"], recursive=False)
    days = iter(
        heading_dates([b.get_text(" ", strip=True) for b in blocks if "date" in b["class"]], today)
    )
    showings, day = [], None
    for block in blocks:
        if "date" in block["class"]:
            day = next(days)
            continue
        start = clock(own_text(block.find("div", class_="time")))
        if day is None or start is None:
            log.warning(
                "Session not understood on %s: %r", heading, block.get_text(" ", strip=True)[:80]
            )
            continue
        when = datetime.combine(day, start, tzinfo=SYDNEY)
        if start < DAY_ROLLOVER:
            when += timedelta(days=1)
        notes = [
            PRICE.sub("", c.get_text(" ", strip=True)).strip()
            for c in block.find_all("div", class_="comment")
        ]
        notes = [n for n in notes if n]
        tags = []
        for note in notes:
            label = NOTES.get(note.lower(), note)
            if label and label not in tags:
                tags.append(label)
        language = block.find("div", class_="language")
        if language and language.get_text(strip=True):
            tags.append(language.get_text(strip=True))
        special = one_off or any(n.lower().startswith("special event") for n in notes)
        book = block.find("a", class_="book")
        session_id = (
            parse_qs(urlsplit(book["href"]).query).get("session_id", [None])[0] if book else None
        )
        showings.append(
            Showing(
                venue_slug=VENUE_SLUG,
                venue_name=VENUE_NAME,
                film_title=page_title,
                start=when,
                session_id=session_id,
                booking_url=book["href"] if book else url,
                attributes=tags,
                film_type="special" if special else "retrospective" if retrospective else None,
                venue_synopsis=synopsis.get_text(" ", strip=True) if synopsis else None,
                runtime_min=int(minutes.group(1)) if minutes else None,
            )
        )
    return showings


class GlenbrookScraper(BaseScraper):
    def fetch(self) -> list[Showing]:
        today = datetime.now(SYDNEY).date()
        showings = []
        for url, labels in film_links(self.get(MOVIES).text):
            found = parse_film(self.get(url).text, today, labels, url)
            showings.extend(s for s in found if not is_non_film(s.film_title))
        return showings


def fetch() -> list[Showing]:
    return GlenbrookScraper().fetch()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    results = fetch()
    for s in results:
        print(
            s.start.strftime("%a %d %b %Y %H:%M"),
            s.film_title,
            s.attributes,
            s.film_type,
            s.runtime_min,
        )
    print(f"{len(results)} showings, {len({s.film_title for s in results})} films")
