"""Roseville Cinemas: the Veezi sessions page, server-rendered with weeks ahead.

https://ticketing.oz.veezi.com/sessions/{siteToken} holds the schedule twice: a
"by date" view (div.date blocks headed "Tuesday 20, October", no year, each with
div.film blocks of session times) and a "by film" view with each film's
description. Sessions come from the by-date view (year from month rollover,
scrapers.heading_dates); descriptions from the by-film view, by title. Each time
links to /purchase/{sessionId}: robots.txt disallows /purchase, so the link is
only linked to, never fetched. Tag codes come from Veezi's own legend.
"""

import logging
import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from models import SYDNEY_TZ, Showing
from scrapers import BaseScraper, heading_dates, is_non_film

log = logging.getLogger("roseville")

SITE_TOKEN = "7feekn7gjsvsvk4xc82a21hja4"
PAGE = f"https://ticketing.oz.veezi.com/sessions/{SITE_TOKEN}"
VENUE_SLUG = "roseville"
VENUE_NAME = "Roseville Cinemas"
# Session tag -> label shown; None drops it. Unlisted tags are kept as written
# and logged.
TAG_LABELS = {
    "CVCC": "Closed Captions",  # CaptiView
    "Interval": "Interval",
    "JIFF": "JIFF",
    "Part Subt": "Partially Subtitled",
    "Sp Ev": "Special Event",
    "Subtitled": "Subtitled",
    "BUY HERE": None,
    "DS Cin 1": None,  # screen
    "US Cin 2": None,  # screen
    "Open Seat": None,  # no allocated seating
    "1 Show": None,  # "One Session Only": availability, not a property
    "LS": None,  # "Limited Season": availability
}
FESTIVAL_TAGS = {"JIFF"}
SPECIAL_TAGS = {"Sp Ev"}
RUNTIME_SUFFIX = re.compile(r",\s*(\d+)\s*['’]\s*$")  # "Monet, 90'"
SESSION_ID = re.compile(r"/purchase/(\d+)")
# A session listed under day D that starts before this belongs to D+1 (DECISIONS.md).
DAY_ROLLOVER = time(5, 0)

SYDNEY = ZoneInfo(SYDNEY_TZ)


def film_type(tags: list[str]) -> str | None:
    if FESTIVAL_TAGS & set(tags):
        return "festival"
    if SPECIAL_TAGS & set(tags):
        return "special"
    return None


def labels(tags: list[str], unknown: set[str] | None = None) -> list[str]:
    shown = []
    for tag in tags:
        if tag in TAG_LABELS:
            label = TAG_LABELS[tag]
        else:
            label = tag
            if unknown is not None:
                unknown.add(tag)
        if label and label not in shown:
            shown.append(label)
    return shown


def runtime(title: str) -> int | None:
    found = RUNTIME_SUFFIX.search(title)
    return int(found.group(1)) if found else None


def descriptions(soup: BeautifulSoup) -> dict[str, str]:
    by_film = soup.find(id="sessionsByFilmConent")  # sic, Veezi's spelling
    found = {}
    for film in by_film.find_all("div", class_="film") if by_film else []:
        title = film.find("h3", class_="title").get_text(strip=True)
        desc = film.find(class_="film-desc")
        if desc:
            found[title] = " ".join(desc.get_text(" ").split())
    return found


def parse_page(html: str, today) -> list[Showing]:
    soup = BeautifulSoup(html, "html.parser")
    by_date = soup.find(id="sessionsByDateConent")  # sic
    days = by_date.find_all("div", class_="date", recursive=False) if by_date else []
    dates = heading_dates([d.find("h3").get_text(" ", strip=True) for d in days], today)
    synopses = descriptions(soup)
    showings, unknown = [], set()
    for block, day in zip(days, dates, strict=True):
        if day is None:
            continue
        for film in block.find_all("div", class_="film"):
            title = film.find("h3", class_="title").get_text(strip=True)
            if is_non_film(title):
                continue
            for item in film.select("ul.session-times li"):
                link = item.find("a", href=True)
                stamp = datetime.strptime(item.find("time").get_text(strip=True), "%I:%M %p")
                at = stamp.time()
                start_day = day + timedelta(days=1) if at < DAY_ROLLOVER else day
                tags = [t.get_text(strip=True) for t in item.select("span.screen-attribute")]
                key = SESSION_ID.search(link["href"]) if link else None
                showings.append(
                    Showing(
                        venue_slug=VENUE_SLUG,
                        venue_name=VENUE_NAME,
                        film_title=title,
                        start=datetime.combine(start_day, at, tzinfo=SYDNEY),
                        session_id=key.group(1) if key else None,
                        booking_url=link["href"] if link else None,
                        attributes=labels(tags, unknown),
                        film_type=film_type(tags),
                        venue_synopsis=synopses.get(title),
                        runtime_min=runtime(title),
                    )
                )
    if unknown:
        log.info("Roseville tags shown as written: %s", ", ".join(sorted(unknown)))
    return showings


class RosevilleScraper(BaseScraper):
    def fetch(self) -> list[Showing]:
        return parse_page(self.get(PAGE).text, datetime.now(SYDNEY).date())


def fetch() -> list[Showing]:
    return RosevilleScraper().fetch()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    results = fetch()
    for s in results[:30]:
        print(s.start.strftime("%a %d %b %Y %H:%M"), s.film_title, s.film_type, s.attributes)
    print(f"{len(results)} showings, {len({s.film_title for s in results})} films")
