"""Fixtures: Event George Street's print view for the week of Thu 15 October
(saved Mon 19 October, so Thu–Sun are already gone) and ?nextWeek=true
(Thu 22 – Wed 28 October), both untrimmed."""

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from scrapers.event import codes, day_dates, labels, parse_week, week_start

SYDNEY = ZoneInfo("Australia/Sydney")
FIXTURES = Path(__file__).parent / "fixtures"
TODAY = date(2026, 10, 19)


@pytest.fixture(scope="module")
def this_week():
    html = (FIXTURES / "event_george-street_2026-10-19.html").read_text(encoding="utf-8")
    return parse_week(html, "george-street", TODAY)


@pytest.fixture(scope="module")
def next_week():
    html = (FIXTURES / "event_george-street_next_2026-10-19.html").read_text(encoding="utf-8")
    return parse_week(html, "george-street", TODAY)


# --- the saved pages ------------------------------------------------------------


def test_fixture_counts(this_week, next_week):
    assert len(this_week) == 205
    assert len(next_week) == 207
    assert {s.start.date() for s in this_week} == {date(2026, 10, d) for d in (19, 20, 21)}
    assert min(s.start.date() for s in next_week) == date(2026, 10, 22)
    assert max(s.start.date() for s in next_week) == date(2026, 10, 28)


def test_fixture_session(this_week):
    s = next(s for s in this_week if s.film_title == "Resident Evil" and s.start.hour == 13)
    assert s.start == datetime(2026, 10, 19, 13, 20, tzinfo=SYDNEY)
    assert (s.venue_slug, s.venue_name) == ("event-george-street", "Event George Street")
    assert s.booking_url == "https://www.eventcinemas.com.au/cinema/george-street"
    assert s.attributes == ["4DX"]  # LOOP dropped
    assert s.runtime_min == 94 and s.session_id is None


def test_one_row_for_several_days(this_week):
    # "Mon Tue 8:30 PM" in 4DX is two sessions.
    fighter = [
        s.start
        for s in this_week
        if s.film_title == "Street Fighter" and "4DX" in s.attributes and s.start.hour == 20
    ]
    assert datetime(2026, 10, 19, 20, 30, tzinfo=SYDNEY) in fighter
    assert datetime(2026, 10, 20, 20, 30, tzinfo=SYDNEY) in fighter


def test_tags_and_types(this_week):
    tags = {a for s in this_week for a in s.attributes}
    assert tags == {
        "4DX",
        "Gold Class",
        "Boutique",
        "Vmax",
        "Audio Description",
        "Closed Captions",
        "Open Captions",
        "Dolby Atmos",
        "NFT",
    }
    hadestown = {s.film_type for s in this_week if s.film_title == "Hadestown: The Musical"}
    assert hadestown == {"special"}  # "Alt Cont"


# --- pieces -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "heading, today, expected",
    [
        ("Thu 15 October - Wed 21 October", TODAY, date(2026, 10, 15)),
        ("Thu 31 December - Wed 6 January", date(2027, 1, 2), date(2026, 12, 31)),
        ("Thu 7 January - Wed 13 January", date(2026, 12, 30), date(2027, 1, 7)),
        ("no week here", TODAY, None),
        ("Thu 29 February - Wed 6 March", date(2028, 2, 20), date(2028, 2, 29)),
    ],
)
def test_week_start(heading, today, expected):
    assert week_start(heading, today) == expected


def test_day_dates_within_thursday_week():
    start = date(2026, 10, 15)  # Thursday
    assert day_dates("Mon Tue", start) == [date(2026, 10, 19), date(2026, 10, 20)]
    assert day_dates("Wed Tue Mon", start) == [date(2026, 10, d) for d in (19, 20, 21)]
    assert day_dates("Thu Sun", start) == [date(2026, 10, 15), date(2026, 10, 18)]


@pytest.mark.parametrize(
    "text, expected",
    [
        ("1:20 PM (LOOP),", ["LOOP"]),
        ("8:30 PM (AD,CC,IR)", ["AD", "CC", "IR"]),
        ("11:00 AM (LOOP,Alt Cont)", ["LOOP", "Alt Cont"]),
        ("6:20 PM (IR,Open Captions)", ["IR", "Open Captions"]),
        ("7:00 PM (Recliner,ENG SUBS,IR,TAMIL)", ["Recliner", "ENG SUBS", "IR", "TAMIL"]),
        ("10:00 AM (LOOP,BRING YOUR BABY)", ["LOOP", "BRING YOUR BABY"]),
        ("7:00 PM", []),
    ],
)
def test_codes(text, expected):
    assert codes(text) == expected


def test_labels():
    unknown = set()
    assert labels(["Recliner", "ATMOS", "IR", "XYZ"], "Gold Class", unknown) == [
        "Gold Class",
        "Dolby Atmos",
        "XYZ",
    ]
    assert labels(["Private Box", "ENG SUBS", "TAMIL", "BRING YOUR BABY"], None, unknown) == [
        "Subtitled",
        "Tamil",
        "Bring Your Baby",
    ]
    assert unknown == {"XYZ"}
