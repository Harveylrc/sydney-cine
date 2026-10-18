from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from scrapers.govindas import clean_title, parse_page

SYDNEY = ZoneInfo("Australia/Sydney")
PAGE = (Path(__file__).parent / "fixtures" / "govindas_movies.html").read_text(encoding="utf-8")
TODAY = date(2026, 10, 19)  # the fixture was saved on Monday 19 October 2026


def test_every_session_with_dates_and_ids():
    showings = parse_page(PAGE, TODAY)
    assert len(showings) == 110
    first = showings[0]
    assert first.start == datetime(2026, 10, 22, 18, 30, tzinfo=SYDNEY)
    assert str(first.start.tzinfo) == "Australia/Sydney"
    assert (first.venue_slug, first.venue_name) == ("govindas", "Govinda's Movie Room")
    assert first.film_title == "Verity (2026)"  # year from the backdrop image
    assert first.session_id == "13091"
    assert first.booking_url == "https://www.govindas.com.au/movie/1128/verity?t=13091"
    assert showings[-1].start.date() == date(2026, 12, 13)  # year carried into December


def test_titles_cleaned():
    titles = {s.film_title for s in parse_page(PAGE, TODAY)}
    assert "The Road to Patagonia" in titles
    assert "Pan's Labyrinth" in titles  # backdrop has no year
    assert not any("BOOKINGS" in t or "Five Stars" in t for t in titles)


def test_movie_only_sessions_tagged():
    movie_only = [s for s in parse_page(PAGE, TODAY) if s.attributes == ["Movie only"]]
    assert movie_only and {s.start.weekday() for s in movie_only} <= {0, 1, 2}  # Mon–Wed


@pytest.mark.parametrize(
    "raw, title, tags",
    [
        ("Verity  BOOKINGS ESSENTIAL MOVIE ONLY RESTAURANT CLOSED", "Verity", ["Movie only"]),
        (
            "Ebenezer BOOKINGS ESSENTIAL MOVIE ONLY RESTAURANT CLOSED (2026)",
            "Ebenezer",
            ["Movie only"],
        ),
        ("The Road to Patagonia (M) Five Stars.. A MUST SEE", "The Road to Patagonia", []),
        (
            "Stanley Kubrick's masterpiece Barry Lyndon THE MOST BEAUTIFUL FILM EVER MADE",
            "Stanley Kubrick's masterpiece Barry Lyndon",
            [],
        ),
        ("NAZA", "NAZA", []),  # one capitalised word is a title, not a slogan
        (
            "The Hunger Games: Sunrise on the Reaping",
            "The Hunger Games: Sunrise on the Reaping",
            [],
        ),
    ],
)
def test_clean_title(raw, title, tags):
    assert clean_title(raw) == (title, tags)
