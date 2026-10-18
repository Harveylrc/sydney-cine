"""Fixture: the Veezi sessions page for Roseville Cinemas, saved 2026-10-19
(Sydney), untrimmed. It holds the schedule twice (by date, by film)."""

import logging
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from scrapers.roseville import film_type, labels, parse_page, runtime

SYDNEY = ZoneInfo("Australia/Sydney")
FIXTURE = Path(__file__).parent / "fixtures" / "roseville_veezi_2026-10-19.html"
TODAY = date(2026, 10, 19)


@pytest.fixture(scope="module")
def showings():
    return parse_page(FIXTURE.read_text(encoding="utf-8"), TODAY)


def by_id(showings, session_id):
    return next(s for s in showings if s.session_id == session_id)


# --- the saved page -------------------------------------------------------------


def test_fixture_counts(showings):
    assert len(showings) == 106  # by-date view only: each session once
    assert len({s.session_id for s in showings}) == 106
    assert len({s.film_title for s in showings}) == 44
    assert {(s.venue_slug, s.venue_name) for s in showings} == {("roseville", "Roseville Cinemas")}


def test_fixture_session(showings):
    s = by_id(showings, "37592")
    assert s.film_title == "Sense and Sensibility"
    assert s.start == datetime(2026, 10, 20, 11, 45, tzinfo=SYDNEY)
    assert s.booking_url == (
        "https://ticketing.oz.veezi.com/purchase/37592?siteToken=7feekn7gjsvsvk4xc82a21hja4"
    )
    assert s.attributes == ["Closed Captions"]  # BUY HERE, screen, Open Seat dropped
    assert s.film_type is None
    assert s.venue_synopsis.startswith("From Focus Features and Working Title")


def test_fixture_types_tags_and_runtime(showings):
    sea = by_id(showings, "37376")  # JIFF 26: The Sea
    assert (sea.film_type, sea.attributes) == ("festival", ["JIFF", "Special Event", "Subtitled"])
    tosca = by_id(showings, "36724")
    assert (tosca.film_type, tosca.attributes) == (
        "special",
        ["Interval", "Special Event", "Subtitled"],
    )
    monet = by_id(showings, "36570")
    assert (monet.film_type, monet.runtime_min) == ("special", 90)


def test_schedule_runs_into_next_year(showings):
    tosca = by_id(showings, "36724")
    assert tosca.start == datetime(2027, 6, 6, 14, 0, tzinfo=SYDNEY)  # AEST, +10:00
    assert tosca.start.utcoffset().total_seconds() == 10 * 3600


def test_every_start_is_sydney_time(showings):
    assert all(s.start.tzinfo == SYDNEY for s in showings)


def test_no_weekday_mismatch(caplog):
    with caplog.at_level(logging.WARNING):
        parse_page(FIXTURE.read_text(encoding="utf-8"), TODAY)
    assert "heading" not in caplog.text


# --- pieces -----------------------------------------------------------------------


def test_labels_mapped_dropped_and_kept():
    unknown = set()
    tags = ["BUY HERE", "CVCC", "DS Cin 1", "Open Seat", "1 Show", "LS", "Part Subt", "Q&A"]
    assert labels(tags, unknown) == ["Closed Captions", "Partially Subtitled", "Q&A"]
    assert unknown == {"Q&A"}


@pytest.mark.parametrize(
    "tags, expected",
    [(["JIFF", "Sp Ev"], "festival"), (["Sp Ev", "Interval"], "special"), (["CVCC"], None)],
)
def test_film_type(tags, expected):
    assert film_type(tags) == expected


@pytest.mark.parametrize(
    "title, minutes",
    [("EXHIBITION ON SCREEN: Monet, 90'", 90), ("Monet, 105’", 105), ("Paris, Texas", None)],
)
def test_runtime(title, minutes):
    assert runtime(title) == minutes
