"""Event Cinemas: the printable week view, /Cinema/Print/{slug} (+ ?nextWeek=true).

Each page covers one Thursday-to-Wednesday week ("Thu 15 October - Wed 21
October" in div.times). Films are grouped by screen type (.screen-type, whose
icon names the format: vmax, gc, 4dx…); each .movie has its title, "(M) 125
mins", an optional "No Free Tickets", and .session-days rows: weekday names
("Mon Tue") with times, each followed by codes in brackets ("(AD CC IR)").
Past days of the current week are left out by Event. The print view has no
booking links or session ids, so showings link to the cinema's page. robots.txt
disallows only /ticketing/ and /tickets/. The page is identical for our
User-Agent and a browser's (checked 2026-10-19: only a Cloudflare token differs).
"""

import logging
import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from models import SYDNEY_TZ, Showing
from scrapers import MONTHS, BaseScraper, is_non_film

log = logging.getLogger("event")

SITE = "https://www.eventcinemas.com.au"
# Greater Sydney metro cinemas (slug -> name). Left out: Glendale and Kotara
# (Newcastle), Shellharbour, Tuggerah (Central Coast), Moonlight (seasonal) and
# Drive In Blacktown (outdoor; see DECISIONS.md).
CINEMAS = {
    "bondi": "Bondi",
    "burwood": "Burwood",
    "campbelltown": "Campbelltown",
    "castle-hill": "Castle Hill",
    "ed-square": "Ed Square",
    "george-street": "George Street",
    "hornsby": "Hornsby",
    "hurstville": "Hurstville",
    "imax-sydney": "IMAX Sydney",
    "liverpool": "Liverpool",
    "macquarie": "Macquarie",
    "miranda": "Miranda",
    "parramatta": "Parramatta",
    "top-ryde-city": "Top Ryde City",
}
# Screen-type icon folder -> format label; None for a standard screen.
SCREEN_TYPES = {
    "std": None,
    "vmax": "Vmax",
    "gc": "Gold Class",
    "boutique": "Boutique",
    "4dx": "4DX",
    "imax": "IMAX",
    "screenx": "ScreenX",
    "eventjr": "Event Junior",  # kids' cinema
}
# Bracketed session codes -> label; None drops it. Unknown codes are kept as
# written and logged.
CODES = {
    "AD": "Audio Description",
    "CC": "Closed Captions",
    "Open Captions": "Open Captions",
    "ATMOS": "Dolby Atmos",
    "Recliner": None,  # seating
    "IR": None,  # infrared hearing system: near-universal
    "LOOP": None,  # hearing loop: near-universal
    "Alt Cont": None,  # "alternative content": becomes film_type special
    "Private Box": None,  # seating
    "ENG SUBS": "Subtitled",
    "BRING YOUR BABY": "Bring Your Baby",
    "Hindi": "Hindi",
    "TAMIL": "Tamil",
    "Mandarin": "Mandarin",
    "Korean": "Korean",
}
SPECIAL_CODES = {"Alt Cont"}
WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
WEEK = re.compile(r"(\d{1,2})\s+(\w+)\s*-\s*\w+\s+(\d{1,2})\s+(\w+)")
CLOCK = re.compile(r"(\d{1,2}):(\d{2})\s*(AM|PM)", re.IGNORECASE)
RUNTIME = re.compile(r"(\d+)\s*mins?", re.IGNORECASE)
# A session listed under day D that starts before this belongs to D+1 (DECISIONS.md).
DAY_ROLLOVER = time(5, 0)

SYDNEY = ZoneInfo(SYDNEY_TZ)


def week_start(text: str, today: date) -> date | None:
    """'Thu 15 October - Wed 21 October' -> 15 October in the right year."""
    found = WEEK.search(text)
    month = MONTHS.get(found.group(2).lower()) if found else None
    if not month:
        return None
    day = int(found.group(1))
    # The year that puts the week nearest today: a page on 2 January may still
    # be headed "Thu 31 December", and one on 30 December "Thu 7 January".
    candidates = []
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            candidates.append(date(year, month, day))
        except ValueError:  # 29 February outside a leap year
            pass
    return min(candidates, key=lambda d: abs(d - today)) if candidates else None


def day_dates(text: str, start: date) -> list[date]:
    """'Mon Tue' within the Thursday-to-Wednesday week starting at start."""
    days = []
    for name in text.split():
        weekday = WEEKDAYS.get(name[:3].lower())
        if weekday is not None:
            days.append(start + timedelta(days=(weekday - start.weekday()) % 7))
    return sorted(days)


def codes(text: str) -> list[str]:
    """'1:20 PM (ENG SUBS,IR,TAMIL),' -> ['ENG SUBS', 'IR', 'TAMIL']."""
    found = re.search(r"\(([^)]*)\)", text)
    return [code.strip() for code in found.group(1).split(",") if code.strip()] if found else []


def labels(session_codes: list[str], screen: str | None, unknown: set[str]) -> list[str]:
    shown = [screen] if screen else []
    for code in session_codes:
        if code in CODES:
            label = CODES[code]
        else:
            label = code
            unknown.add(code)
        if label and label not in shown:
            shown.append(label)
    return shown


def screen_label(section, unknown: set[str]) -> str | None:
    icon = section.select_one(".title img")
    found = re.search(r"/sessionhover/([^/]+)/", icon["src"]) if icon else None
    name = found.group(1).lower() if found else "std"
    if name not in SCREEN_TYPES:
        unknown.add(f"screen:{name}")
        return name.upper()
    return SCREEN_TYPES[name]


def parse_week(html: str, slug: str, today: date, unknown: set[str] | None = None) -> list[Showing]:
    unknown = unknown if unknown is not None else set()
    soup = BeautifulSoup(html, "html.parser")
    header = soup.select_one("div.times")
    start = week_start(header.get_text(" ", strip=True), today) if header else None
    if start is None:
        log.warning("Event %s: week heading not understood", slug)
        return []
    showings = []
    for section in soup.select(".screen-type"):
        screen = screen_label(section, unknown)
        for movie in section.select(".movie"):
            title = movie.select_one(".movie-title").get_text(" ", strip=True)
            if is_non_film(title):
                continue
            info = movie.select_one(".movie-title").find_next_sibling("span")
            info_text = info.get_text(" ", strip=True) if info else ""
            runtime = RUNTIME.search(info_text)
            nft = "No Free Tickets" in info_text
            for row in movie.select(".session-days"):
                days = day_dates(row.find("b").get_text(" ", strip=True), start)
                for slot in row.find_all("span", recursive=False):
                    text = slot.get_text(" ", strip=True)
                    clock = CLOCK.search(text)
                    if not clock:
                        continue
                    hour = int(clock.group(1)) % 12 + (12 if clock.group(3).upper() == "PM" else 0)
                    at = time(hour, int(clock.group(2)))
                    session_codes = codes(text)
                    tags = labels(session_codes, screen, unknown) + (["NFT"] if nft else [])
                    for day in days:
                        if at < DAY_ROLLOVER:
                            day += timedelta(days=1)
                        showings.append(
                            Showing(
                                venue_slug=f"event-{slug}",
                                venue_name=f"Event {CINEMAS[slug]}",
                                film_title=title,
                                start=datetime.combine(day, at, tzinfo=SYDNEY),
                                booking_url=f"{SITE}/cinema/{slug}",
                                attributes=tags,
                                film_type="special" if SPECIAL_CODES & set(session_codes) else None,
                                runtime_min=int(runtime.group(1)) if runtime else None,
                            )
                        )
    return showings


class EventScraper(BaseScraper):
    def fetch(self) -> list[Showing]:
        today = datetime.now(SYDNEY).date()
        showings, unknown = [], set()
        for slug in CINEMAS:
            for suffix in ("", "?nextWeek=true"):
                page = self.get(f"{SITE}/Cinema/Print/{slug}{suffix}").text
                showings.extend(parse_week(page, slug, today, unknown))
        if unknown:
            log.info("Event codes shown as written: %s", ", ".join(sorted(unknown)))
        return showings


def fetch() -> list[Showing]:
    return EventScraper().fetch()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    results = fetch()
    for s in results[:30]:
        print(s.venue_name, s.start.strftime("%a %d %b %H:%M"), s.film_title, s.attributes)
    print(f"{len(results)} showings, {len({s.film_title for s in results})} films")
