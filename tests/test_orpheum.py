"""Fixture: /api/movie/playing-now saved 2026-10-18, trimmed for size (image and
trailer URLs dropped; each film's duplicated "director" copy cut to its names).
Sessions are untouched."""

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from scrapers.orpheum import (
    attributes,
    director,
    film_type,
    minutes,
    parse_films,
    plain_text,
    start_time,
)

SYDNEY = ZoneInfo("Australia/Sydney")
FIXTURE = Path(__file__).parent / "fixtures" / "orpheum_playing-now_2026-10-18.json"


@pytest.fixture(scope="module")
def showings():
    return parse_films(json.loads(FIXTURE.read_text(encoding="utf-8")))


def by_id(showings, session_id):
    return next(s for s in showings if s.session_id == session_id)


# --- the saved response -------------------------------------------------------


def test_fixture_counts(showings):
    assert len(showings) == 253  # 258 listed, less 5 Jazz Lounge / Comedy Club nights
    assert len({s.film_title for s in showings}) == 100
    assert not any("Jazz Lounge" in s.film_title or "Comedy Club" in s.film_title for s in showings)
    assert {(s.venue_slug, s.venue_name) for s in showings} == {("orpheum", "Hayden Orpheum")}


def test_fixture_session(showings):
    s = by_id(showings, "0001-26248")
    assert s.film_title == "Verity"
    assert s.start == datetime(2026, 10, 19, 15, 30, tzinfo=SYDNEY)
    assert s.booking_url == "https://web.orpheum.com.au/order/showtimes/0001-26248/tickets"
    assert s.attributes == ["Audio Description", "Closed Captions"]  # "HI" dropped
    assert s.runtime_min == 117
    assert s.venue_synopsis.startswith("Struggling writer Lowen Ashleigh")
    assert s.film_type is None


def test_fixture_film_types_and_formats(showings):
    psycho = by_id(showings, "0001-24692")
    assert (psycho.film_type, psycho.runtime_min) == ("retrospective", 109)
    assert by_id(showings, "0001-25529").attributes == ["70mm"]  # Lawrence of Arabia
    assert by_id(showings, "0001-25974").film_type == "special"  # The Fox - Q&A Preview
    assert psycho.venue_director == "Alfred Hitchcock"
    pitfall = by_id(showings, "0001-25021")
    assert (pitfall.film_type, pitfall.attributes) == ("festival", ["Subtitled"])


def test_every_start_is_sydney_time(showings):
    assert all(s.start.tzinfo == SYDNEY for s in showings)


def test_synopsis_html_stripped(showings):
    frozen = next(s for s in showings if s.film_title == "Frozen - Sing-A-Long")
    assert "<br" not in frozen.venue_synopsis
    assert "Fun for the whole family! Young princess Anna" in frozen.venue_synopsis


# --- pieces -------------------------------------------------------------------


@pytest.mark.parametrize(
    "day, clock, expected",
    [
        ("2026-10-19", "3:30pm", datetime(2026, 10, 19, 15, 30)),
        ("2026-10-19", "12:10pm", datetime(2026, 10, 19, 12, 10)),
        ("2026-10-19", "10:15am", datetime(2026, 10, 19, 10, 15)),
        ("2026-10-24", "12:30am", datetime(2026, 10, 25, 0, 30)),  # listed Sat, starts Sun
        ("2027-06-01", "7:00pm", datetime(2027, 6, 1, 19, 0)),  # AEST
    ],
)
def test_start_time(day, clock, expected):
    assert start_time(day, clock) == expected.replace(tzinfo=SYDNEY)


def test_attributes_mapped_dropped_and_kept():
    unknown = set()
    session = {
        "attributes": [
            {"shortName": "NFT", "description": "No Free Tickets"},
            {"shortName": "HI", "description": "Hearing Impaired"},
            {"shortName": "35MM", "description": "35mm Film Print"},
        ]
    }
    assert attributes(session, unknown) == ["NFT", "35mm Film Print"]
    assert unknown == {"35MM"}


@pytest.mark.parametrize(
    "title, expected",
    [
        ("JFF 2026 - Pitfall on 35mm Film", "festival"),
        ("Ocean Film Festival World Tour 2027", "festival"),
        ("Hitchcok Retro - Rebecca 4K Restoration", "retrospective"),
        ("The Fox - Q&A Preview", "special"),
        ("Met Opera - Macbeth", "special"),
        ("Two of Us - The Songs of Simon & Garfunkel Live", "special"),
        ("Casino Royale - 20th Anniversary 4K Restoration", None),  # year rule decides
        ("Verity", None),
    ],
)
def test_film_type(title, expected):
    assert film_type(title) == expected


@pytest.mark.parametrize("raw, expected", [("102", 102), (95, 95), ("", None), (None, None)])
def test_minutes(raw, expected):
    assert minutes(raw) == expected


def test_plain_text():
    assert plain_text("One.<br /><br />Two &amp; three.") == "One. Two & three."
    assert plain_text("") is None


def test_director():
    assert (
        director({"director": {"director": ["Joel Coen", " Ethan Coen "]}})
        == "Joel Coen, Ethan Coen"
    )
    assert director({"director": {"director": []}}) is None
    assert director({}) is None
