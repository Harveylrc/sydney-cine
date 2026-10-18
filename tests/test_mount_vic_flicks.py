from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from scrapers.mount_vic_flicks import PRESENTED, clock, film_type, parse_page

SYDNEY = ZoneInfo("Australia/Sydney")
PAGE = (Path(__file__).parent / "fixtures" / "mount_vic_flicks_sessions.html").read_text(
    encoding="utf-8"
)  # saved 19 October 2026


def by_title(title):
    return [s for s in parse_page(PAGE) if s.film_title == title]


def test_every_session():
    showings = parse_page(PAGE)
    assert len(showings) == 12
    assert {s.venue_slug for s in showings} == {"mount-vic-flicks"}
    assert {s.venue_name for s in showings} == {"Mount Vic Flicks"}
    assert all(str(s.start.tzinfo) == "Australia/Sydney" for s in showings)


def test_two_sessions_of_one_film_on_one_day():
    sense = by_title("Sense and Sensibility")
    assert [s.start for s in sense] == [
        datetime(2026, 10, 21, 13, 20, tzinfo=SYDNEY),
        datetime(2026, 10, 21, 18, 0, tzinfo=SYDNEY),
    ]
    assert sense[0].session_id == "20261012-145634"
    assert (
        sense[0].booking_url
        == "https://mountvicflicks.com.au/sessions/sense-and-sensibility/20261012-145634/"
    )
    assert sense[0].film_type is None and sense[0].attributes == []


def test_presentation_note_becomes_tag_and_type():
    [advance, _] = by_title("Wicker")
    assert advance.attributes == ["Advance Screening"] and advance.film_type == "new_release"
    [halloween] = by_title("Night of the Living Dead")
    assert halloween.attributes == ["Halloween Special"] and halloween.film_type == "special"
    [climber] = by_title("Girl Climber")
    assert climber.attributes == ["One screening only"] and climber.film_type == "special"


def test_event_with_price_links_to_trybooking():
    [reel_rock] = by_title("Reel Rock 20")
    assert reel_rock.start == datetime(2026, 11, 16, 18, 30, tzinfo=SYDNEY)
    assert reel_rock.booking_url == "https://www.trybooking.com/DQAMF"
    assert reel_rock.session_id is None


@pytest.mark.parametrize(
    "title, kept",
    [
        ("Mission: Impossible - Dead Reckoning", True),  # a real subtitle stays
        ("Wicker - Advance Screening", False),
        ("Pan's Labyrinth - 20th Anniversary", False),
    ],
)
def test_only_presentation_suffixes_are_split(title, kept):
    assert (PRESENTED.search(title) is None) is kept


def test_clock_and_type():
    assert clock("6:30 pm (Tickets $20/15 +BF)") == time(18, 30)
    assert clock("11:00 am") == time(11, 0) and clock("More") is None
    assert film_type(None) is None and film_type("20th Anniversary") == "retrospective"
