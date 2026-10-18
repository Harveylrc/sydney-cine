"""Fixture: /films/now-showing saved 2026-10-18 (Sydney), untrimmed. Besides the
rendered HTML the scraper reads, the page embeds the same schedule as data with
full dates (eventDate); the tests use that to check the inferred years."""

import json
import logging
import re
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from scrapers.golden_age import clock, credits, heading_dates, parse_page

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
        if t["contentType"] == "film"
    ]


# --- the saved page -------------------------------------------------------------


def test_fixture_counts(showings):
    assert len(showings) == 60
    assert len({s.film_title for s in showings}) == 35
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


def test_notices_skipped_and_events_kept(showings):
    titles = {s.film_title for s in showings}
    assert not any("Closed" in t for t in titles)
    trivia = next(s for s in showings if s.film_title == "Film Trivia")
    assert (trivia.venue_director, trivia.runtime_min) == (None, None)


def test_co_directors(showings):
    naza = next(s for s in showings if s.film_title == "NAZA")
    assert naza.venue_director == "Yuval Abraham, Rachel Szor"


# --- year inference ---------------------------------------------------------------


def test_month_rollover_into_next_year():
    headings = ["Wednesday 30th December", "Thursday 31st December", "Friday 1st January"]
    assert heading_dates(headings, date(2026, 12, 30)) == [
        date(2026, 12, 30),
        date(2026, 12, 31),
        date(2027, 1, 1),
    ]


def test_first_heading_long_past_means_next_year():
    assert heading_dates(["Saturday 2nd January"], date(2026, 12, 30)) == [date(2027, 1, 2)]


def test_first_heading_a_little_past_stays_this_year():
    # A page cached a day behind: still this year.
    assert heading_dates(["Saturday 17th October"], TODAY) == [date(2026, 10, 17)]


def test_wrong_weekday_logged(caplog):
    with caplog.at_level(logging.WARNING, logger="golden_age"):
        assert heading_dates(["Monday 18th October"], TODAY) == [date(2026, 10, 18)]
    assert "is not a Monday in 2026" in caplog.text


@pytest.mark.parametrize("bad", ["Sunday 29th February", "Coming soon"])
def test_unusable_heading_skipped(bad, caplog):
    with caplog.at_level(logging.WARNING, logger="golden_age"):
        assert heading_dates([bad], TODAY) == [None]


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
