from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from scrapers import manual

SYDNEY = ZoneInfo("Australia/Sydney")
FIXTURES = Path(__file__).parent / "fixtures" / "manual"
NOW = datetime(2026, 10, 19, 9, 0, tzinfo=SYDNEY)


def test_sessions_already_started_are_dropped():
    data = {
        "venue": "v",
        "name": "V",
        "sessions": [
            {"date": "2026-10-19", "time": "08:59", "title": "Started"},
            {"date": "2026-10-19", "time": "09:00", "title": "Starting now"},
            {"date": "2026-10-20", "time": "19:00", "title": "Tomorrow"},
        ],
    }
    assert [s.film_title for s in manual.parse_file(data, NOW)] == ["Starting now", "Tomorrow"]


def test_fixture_file():
    showings = manual.fetch(FIXTURES, NOW)
    assert [s.film_title for s in showings] == [
        "Vivre sa vie (1962)",
        "A New Film",
    ]  # past one dropped
    vivre, new_film = showings
    assert vivre.start == datetime(2026, 10, 22, 19, 0, tzinfo=SYDNEY)
    assert str(vivre.start.tzinfo) == "Australia/Sydney"
    assert (vivre.venue_slug, vivre.venue_name) == ("test-venue", "Test Venue")
    assert vivre.venue_director == "Jean-Luc Godard" and vivre.attributes == ["35mm"]
    assert vivre.film_type == "retrospective"  # the file's default
    assert vivre.booking_url == "https://example.org/programme"  # no url: the source page
    assert new_film.film_type == "new_release" and new_film.booking_url.endswith("a-new-film")


def test_unknown_type_rejected():
    data = {
        "venue": "v",
        "name": "V",
        "sessions": [{"date": "2026-10-22", "time": "19:00", "title": "X", "type": "gala"}],
    }
    with pytest.raises(ValueError, match="gala"):
        manual.parse_file(data, NOW)


def test_no_files_no_showings(tmp_path):
    assert manual.fetch(tmp_path, NOW) == []


@pytest.mark.parametrize("value, expected", [("19:00", (19, 0)), ("7:05", (7, 5)), (1140, (19, 0))])
def test_clock(value, expected):
    assert (manual.clock(value).hour, manual.clock(value).minute) == expected


def test_shipped_manual_files_parse():
    for data in manual.load():
        manual.parse_file(data, NOW)  # raises on a bad entry
    assert manual.parse_file({"venue": "v", "name": "V", "sessions": []}, NOW) == []
