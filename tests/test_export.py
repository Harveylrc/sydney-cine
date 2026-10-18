import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from export import build_data, display_day, effective_type, load_previous, time_label, write
from models import Showing
from scrapers.ritz import parse_day

SYDNEY = ZoneInfo("Australia/Sydney")
FIXTURES = Path(__file__).parent / "fixtures"
LAUNCH = date(2026, 10, 16)


def at(day, hour, minute=0):
    return datetime.combine(day, datetime.min.time(), tzinfo=SYDNEY).replace(
        hour=hour, minute=minute
    )


def showing(title, start, venue="ritz-randwick", **kw):
    return Showing(
        venue_slug=venue,
        venue_name={"ritz-randwick": "Ritz Randwick", "orpheum": "Hayden Orpheum"}[venue],
        film_title=title,
        start=start,
        **kw,
    )


# --- late night ---------------------------------------------------------------


@pytest.mark.parametrize(
    "hour, minute, expected",
    [
        (0, 30, date(2026, 10, 16)),  # Sat 00:30 -> Fri
        (4, 59, date(2026, 10, 16)),
        (5, 0, date(2026, 10, 17)),
        (23, 45, date(2026, 10, 17)),
    ],
)
def test_display_day(hour, minute, expected):
    assert display_day(at(date(2026, 10, 17), hour, minute)) == expected


def test_saturday_0030_listed_under_friday_with_true_start():
    sat = at(date(2026, 10, 17), 0, 30)
    data = build_data([showing("Possession", sat, film_type="special")], None, LAUNCH)
    [row] = data["showings"]
    assert row["day"] == "2026-10-16"
    assert row["late"] is True
    assert row["time"] == "12:30 am"
    assert row["start"] == "2026-10-17T00:30:00+11:00"


@pytest.mark.parametrize(
    "hour, minute, label",
    [(0, 30, "12:30 am"), (7, 0, "7:00 am"), (12, 0, "12:00 pm"), (13, 5, "1:05 pm")],
)
def test_time_label(hour, minute, label):
    assert time_label(at(LAUNCH, hour, minute)) == label


# --- film type fallback -------------------------------------------------------


@pytest.mark.parametrize(
    "film_type, year, expected",
    [
        ("festival", 1967, "festival"),  # venue's type always wins
        (None, 2024, "retrospective"),  # 2026 - 2
        (None, 2025, "new_release"),
        (None, None, None),
    ],
)
def test_effective_type(film_type, year, expected):
    s = showing("X", at(LAUNCH, 19), film_type=film_type, year=year)
    assert effective_type(s, 2026) == expected


# --- films and ids ------------------------------------------------------------


def test_same_tmdb_film_under_two_venue_titles_is_one_film():
    data = build_data(
        [
            showing("La Bola Negra", at(LAUNCH, 13), tmdb_id=7, year=2026),
            showing("35mm La Bola Negra", at(LAUNCH, 19), tmdb_id=7, year=2026),
        ],
        None,
        LAUNCH,
    )
    [film] = data["films"]
    assert film["id"] == "tmdb:7" and film["title"] == "La Bola Negra"
    assert [r["title"] for r in data["showings"]] == ["La Bola Negra", "35mm La Bola Negra"]


def test_unmatched_film_keyed_by_cleaned_title():
    data = build_data([showing("JIFF: The Sea", at(LAUNCH, 19))], None, LAUNCH)
    assert data["films"][0]["id"] == "title:thesea"
    assert data["films"][0]["title"] == "The Sea"


# --- new this week ------------------------------------------------------------


def run_days(days):
    """days: list of (date, showings). Feeds each export into the next."""
    data = None
    for day, showings in days:
        data = build_data(showings, data, day)
    return data


def new_flags(data):
    return {f["title"]: f["new_this_week"] for f in data["films"]}


def test_launch_day_films_are_not_new():
    data = build_data([showing("Old Film", at(LAUNCH, 19))], None, LAUNCH)
    assert new_flags(data) == {"Old Film": False}


def test_film_appearing_after_launch_is_new():
    d2 = LAUNCH + timedelta(days=1)
    data = run_days(
        [
            (LAUNCH, [showing("Old Film", at(LAUNCH, 19))]),
            (
                d2,
                [showing("Old Film", at(d2, 19)), showing("Fresh Film", at(d2 + timedelta(3), 19))],
            ),
        ]
    )
    assert new_flags(data) == {"Old Film": False, "Fresh Film": True}
    fresh = next(f for f in data["films"] if f["title"] == "Fresh Film")
    assert fresh["first_seen"] == d2.isoformat()


@pytest.mark.parametrize("days_later, expected", [(6, True), (7, False)])
def test_new_lasts_seven_days(days_later, expected):
    d2 = LAUNCH + timedelta(days=1)
    later = d2 + timedelta(days=days_later)
    data = run_days(
        [
            (LAUNCH, [showing("Old Film", at(LAUNCH, 19))]),
            (d2, [showing("Fresh Film", at(d2, 19))]),
            (later, [showing("Fresh Film", at(later, 19))]),
        ]
    )
    assert new_flags(data)["Fresh Film"] is expected


def test_adding_a_venue_does_not_make_its_films_new():
    d5 = LAUNCH + timedelta(days=5)
    data = run_days(
        [
            (LAUNCH, [showing("Ritz Film", at(LAUNCH, 19))]),
            (
                d5,
                [
                    showing("Ritz Film", at(d5, 19)),
                    showing("Orpheum Film", at(d5, 19), venue="orpheum"),
                ],
            ),
        ]
    )
    assert new_flags(data) == {"Ritz Film": False, "Orpheum Film": False}
    assert data["venues"]["orpheum"]["first_seen"] == d5.isoformat()


def test_film_new_at_established_venue_on_the_day_another_venue_is_added():
    d5 = LAUNCH + timedelta(days=5)
    data = run_days(
        [
            (LAUNCH, [showing("Ritz Film", at(LAUNCH, 19))]),
            (
                d5,
                [
                    showing("Shared Premiere", at(d5, 19)),
                    showing("Shared Premiere", at(d5, 20), venue="orpheum"),
                ],
            ),
        ]
    )
    assert new_flags(data)["Shared Premiere"] is True


def test_first_seen_survives_a_gap():
    d2, d3, d4 = (LAUNCH + timedelta(days=n) for n in (1, 2, 3))
    data = run_days(
        [
            (LAUNCH, [showing("Old Film", at(LAUNCH, 19))]),
            (d2, [showing("Returning", at(d2, 19))]),
            (d3, [showing("Old Film", at(d3, 19))]),  # Returning not listed
            (d4, [showing("Returning", at(d4, 19))]),
        ]
    )
    returning = next(f for f in data["films"] if f["title"] == "Returning")
    assert returning["first_seen"] == d2.isoformat()


# --- real fixture + file round trip -------------------------------------------


def test_fixture_day_exports(tmp_path):
    html = (FIXTURES / "ritz_2026-10-16.html").read_text(encoding="utf-8")
    data = build_data(parse_day(html, LAUNCH), None, LAUNCH)
    assert len(data["showings"]) == 40
    assert len(data["films"]) == 22
    assert {r["day"] for r in data["showings"]} == {"2026-10-16"}
    assert data["venues"] == {
        "ritz-randwick": {"name": "Ritz Randwick", "first_seen": "2026-10-16"}
    }
    path = tmp_path / "public" / "data.json"
    write(data, path)
    assert load_previous(path) == json.loads(json.dumps(data))
    assert "Léon" in path.read_text(encoding="utf-8")  # UTF-8, not \\u escapes


def test_missing_previous_is_none(tmp_path):
    assert load_previous(tmp_path / "nope.json") is None


def test_film_carries_vote_count():
    s = showing("Akira (1988)", at(LAUNCH, 19), tmdb_id=149, year=1988, vote_count=5200)
    [film] = build_data([s], None, LAUNCH)["films"]
    assert film["vote_count"] == 5200


# --- horizon and hidden tags --------------------------------------------------


@pytest.mark.parametrize(
    "start, kept",
    [
        (at(LAUNCH, 10), True),  # today
        (at(LAUNCH, 2), False),  # 02:00 today belongs to yesterday evening
        (at(LAUNCH + timedelta(days=13), 21), True),  # 14th day
        (at(LAUNCH + timedelta(days=14), 1), True),  # late night of the 14th day
        (at(LAUNCH + timedelta(days=14), 10), False),  # 15th day
        (at(LAUNCH - timedelta(days=1), 19), False),
    ],
)
def test_horizon(start, kept):
    data = build_data([showing("Film", start)], None, LAUNCH)
    assert bool(data["showings"]) is kept


def test_film_beyond_horizon_is_not_seen_yet():
    data = build_data([showing("Far Off", at(LAUNCH + timedelta(days=60), 19))], None, LAUNCH)
    assert data["films"] == [] and data["seen"] == {}


def test_audio_description_and_closed_captions_dropped():
    tags = ["Xtremescreen", "Audio Description", "Closed Captions", "Open Captions"]
    [row] = build_data([showing("Film", at(LAUNCH, 19), attributes=tags)], None, LAUNCH)["showings"]
    assert row["attributes"] == ["Xtremescreen", "Open Captions"]


def test_not_a_film_dropped_and_logged(caplog):
    shows = [
        showing("Film", at(LAUNCH, 19)),
        showing("Tribute Band Live", at(LAUNCH, 20), is_film=False),
    ]
    with caplog.at_level(logging.INFO, logger="export"):
        data = build_data(shows, None, LAUNCH)
    assert [r["title"] for r in data["showings"]] == ["Film"]
    assert "Dropped, not a film: 'Tribute Band Live' at Ritz Randwick" in caplog.text
