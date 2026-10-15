from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from models import Showing
from scrapers.ritz import parse_day

SYDNEY = ZoneInfo("Australia/Sydney")
FIXTURE = Path(__file__).parent / "fixtures" / "ritz_2026-10-16.html"
DAY = date(2026, 10, 16)


@pytest.fixture(scope="module")
def showings():
    return parse_day(FIXTURE.read_text(encoding="utf-8"), DAY)


def showing(title, hour, minute, session_id, attributes=()):
    return Showing(
        venue_slug="ritz-randwick",
        venue_name="Ritz Randwick",
        film_title=title,
        start=datetime(2026, 10, 16, hour, minute, tzinfo=SYDNEY),
        session_id=session_id,
        booking_url=f"https://www.ritzcinemas.com.au/tickets?c=0000000004&s={session_id}",
        attributes=list(attributes),
    )


def test_counts(showings):
    assert len(showings) == 40
    assert len({s.film_title for s in showings}) == 22
    assert len({s.session_id for s in showings}) == 40


def test_all_on_requested_day_in_sydney(showings):
    assert all(s.start.date() == DAY and s.start.tzinfo is SYDNEY for s in showings)


@pytest.mark.parametrize(
    "expected",
    [
        showing("La Bola Negra", 13, 0, "92920", ["NFT"]),
        showing("Verity", 10, 20, "93139"),
        showing("35mm Léon: The Professional (1994)", 20, 0, "78345", ["35MM", "RETRO"]),
        showing(
            "Labyrinth – 40th Anniversary Live Show & Screening",
            19,
            30,
            "86637",
            ["LiveMusic", "Selling Fast"],
        ),
        showing("Ranabaali", 7, 0, "92974"),
    ],
    ids=lambda s: s.film_title,
)
def test_expected_showings(showings, expected):
    assert expected in showings


def test_comma_joined_tags_split(showings):
    qa = [s for s in showings if "Q&A" in s.attributes]
    assert len(qa) == 1 and qa[0].attributes == ["NFT", "Q&A"]


def test_empty_page():
    assert parse_day("<html><body></body></html>", DAY) == []
