"""Fixture: /films/now-showing saved 2026-10-18 (Sydney), untrimmed. Besides the
rendered HTML the scraper reads, the page embeds the same schedule as data with
full dates (eventDate); the tests use that to check the inferred years."""

import json
import re
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from scrapers.golden_age import clock, credits, parse_page

SYDNEY = ZoneInfo("Australia/Sydney")
FIXTURE = Path(__file__).parent / "fixtures" / "golden_age_2026-10-18.html"
TODAY = date(2026, 10, 18)


@pytest.fixture(scope="module")
def html():
    return FIXTURE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def showings(html):
    return parse_page(html, TODAY)


def embedded_schedule(html):
    """The page's own (title, eventDate) list for films, from its Next.js data."""
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', html, re.S)
    flight = "".join(json.loads('"' + c + '"') for c in chunks)
    data, _ = json.JSONDecoder().raw_decode(flight, flight.index('{"groupedThumbData":'))
    return [
        (t["title"], t["eventDate"])
        for group in data["groupedThumbData"]
        for t in group["thumbs"]
        if t["contentType"] == "film" and t["title"] != "Film Trivia"
    ]


# --- the saved page -------------------------------------------------------------


def test_fixture_counts(showings):
    assert len(showings) == 57  # 60 film-page sessions, less 3 Film Trivia nights
    assert len({s.film_title for s in showings}) == 34
    assert {(s.venue_slug, s.venue_name) for s in showings} == {("golden-age", "Golden Age")}


def test_every_session_matches_the_pages_own_dates(html, showings):
    mine = [(s.film_title, s.start.strftime("%Y-%m-%dT%H:%M:%S")) for s in showings]
    assert mine == embedded_schedule(html)


def test_fixture_session(showings):
    s = showings[0]
    assert s.film_title == "Loves of a Blonde"
    assert s.start == datetime(2026, 10, 18, 11, 0, tzinfo=SYDNEY)
    assert (s.venue_director, s.runtime_min) == ("Miloš Forman", 81)
    assert s.booking_url == "https://www.ourgoldenage.com.au/film/loves-of-a-blonde"
    assert s.attributes == [] and s.session_id is None and s.film_type is None


def test_notices_and_non_film_events_skipped(showings):
    titles = {s.film_title for s in showings}
    assert not any("Closed" in t for t in titles)
    assert "Film Trivia" not in titles


def test_co_directors(showings):
    naza = next(s for s in showings if s.film_title == "NAZA")
    assert naza.venue_director == "Yuval Abraham, Rachel Szor"


# --- pieces -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Sun 18 11:00 am", time(11, 0)),
        ("Mon 19 12:30 pm", time(12, 30)),
        ("Fri 23 7:50 pm", time(19, 50)),
        ("Sat 24 12:15 am", time(0, 15)),
        ("no time", None),
    ],
)
def test_clock(text, expected):
    assert clock(text) == expected


@pytest.mark.parametrize(
    "subtitle, expected",
    [
        ("Dir. Miloš Forman | 81mins", ("Miloš Forman", 81)),
        ("Dir. Jacques Rivette | 193 mins", ("Jacques Rivette", 193)),
        ("Dir. Agnès Varda", ("Agnès Varda", None)),
        ("", (None, None)),
        ("from 7:00pm", (None, None)),
        ("Dir. ??? | 95mins", (None, 95)),
    ],
)
def test_credits(subtitle, expected):
    assert credits(subtitle) == expected
