import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from scrapers.hoyts import attributes, film_type, movie_index, parse_sessions, start_time

SYDNEY = ZoneInfo("Australia/Sydney")
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def movies():
    return movie_index(json.loads((FIXTURES / "hoyts_movies_2026-10-18.json").read_text()))


@pytest.fixture(scope="module")
def showings(movies):
    sessions = json.loads((FIXTURES / "hoyts_sessions_SHOWGR_2026-10-18.json").read_text())
    return parse_sessions(sessions, movies)


def by_id(showings, session_id):
    return next(s for s in showings if s.session_id == session_id)


def session(**kw):
    base = {
        "id": 1,
        "cinemaId": "BROADW",
        "movieId": "HO1",
        "date": "2026-10-18T19:00:00",
        "utcDate": "2026-10-18T08:00:00+00:00",
        "typeId": "STANDARD",
        "originalTags": [],
    }
    return base | kw


MOVIE = {"vistaId": "HO1", "name": "Some Film", "genres": ["Drama"]}


# --- the saved Entertainment Quarter response ---------------------------------


def test_fixture_counts(showings):
    assert len(showings) == 443
    assert len({s.film_title for s in showings}) == 30
    assert {s.venue_slug for s in showings} == {"hoyts-entertainment-quarter"}
    assert {s.venue_name for s in showings} == {"Hoyts Entertainment Quarter"}


def test_fixture_session(showings):
    s = by_id(showings, "512493")
    assert s.film_title == "Avengers: Doomsday"
    assert s.start == datetime(2026, 12, 16, 18, 0, tzinfo=SYDNEY)
    assert s.start.utcoffset().total_seconds() == 11 * 3600
    assert (
        s.booking_url == "https://www.hoyts.com.au/orders/tickets?cinemaId=SHOWGR&sessionId=512493"
    )
    assert s.attributes == [
        "Xtremescreen",
        "Audio Description",
        "Closed Captions",
        "Infinity Vision",
    ]
    assert s.vista_movie_id == "HO00008129"  # Doomsday's second Vista id
    assert s.runtime_min == 165
    assert s.venue_synopsis is None  # Hoyts: runtime only (DECISIONS 2026-10-18)
    assert s.film_type is None


def test_sold_out_session_has_no_booking_link(showings):
    s = by_id(showings, "512494")
    assert s.booking_url is None
    assert s.attributes == ["LUX", "Audio Description", "Closed Captions"]


def test_fixture_film_types(showings):
    special = {s.film_title for s in showings if s.film_type == "special"}
    assert special == {
        "The Songs of John Farnham: Celebration Concert Encore",  # genre Concert
        "George Michael: The Faith Tour",
        "The Hunger Games: Sunrise on the Reaping",  # SPECEVENT sessions only
    }


def test_every_start_is_sydney_time(showings):
    assert all(s.start.tzinfo == SYDNEY for s in showings)


# --- pieces -------------------------------------------------------------------


def test_movie_with_several_vista_ids():
    index = movie_index([{"vistaId": "HO00008129,HO00011223", "name": "Avengers: Doomsday"}])
    assert index["HO00008129"] is index["HO00011223"]


def test_non_sydney_cinema_skipped():
    assert parse_sessions([session(cinemaId="CHARLE")], {"HO1": MOVIE}) == []


def test_unknown_movie_skipped():
    assert parse_sessions([session(movieId="HO2")], {"HO1": MOVIE}) == []


@pytest.mark.parametrize(
    "utc, local, expected",
    [
        ("2026-10-18T08:00:00+00:00", "2026-10-18T19:00:00", datetime(2026, 10, 18, 19, 0)),
        ("2026-06-01T09:00:00+00:00", "2026-06-01T19:00:00", datetime(2026, 6, 1, 19, 0)),  # AEST
        ("0001-01-01T00:00:00+00:00", "2026-10-18T10:00:00", datetime(2026, 10, 18, 10, 0)),
    ],
)
def test_start_time(utc, local, expected):
    start = start_time(session(utcDate=utc, date=local))
    assert start == expected.replace(tzinfo=SYDNEY)


def test_attributes_readable_dropped_and_unknown():
    unknown = set()
    tags = ["RC", "IMAX", "AD", "CC", "DISCOUNT", "GNO", "OC"]
    assert attributes(session(typeId="IMAX", originalTags=tags), unknown) == [
        "IMAX",
        "Audio Description",
        "Closed Captions",
        "Open Captions",
    ]
    assert unknown == {"GNO"}


@pytest.mark.parametrize(
    "name, genres, tags, expected",
    [
        ("(LFF) Liste De Marriage", ["Comedy"], ["SPECEVENT"], "festival"),
        ("Hadestown: The Musical", ["Main Stage"], [], "special"),
        ("Parkway Drive: Home", ["Concert"], [], "special"),
        ("The Odyssey", ["Action"], ["SPECEVENT"], "special"),
        ("The Odyssey", ["Action"], ["AD"], None),
    ],
)
def test_film_type(name, genres, tags, expected):
    movie = {"vistaId": "HO1", "name": name, "genres": genres}
    assert film_type(movie, session(originalTags=tags)) == expected
