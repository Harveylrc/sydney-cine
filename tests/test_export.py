import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from export import (
    REGIONS,
    build_data,
    build_film_details,
    display_day,
    effective_type,
    load_previous,
    load_venues,
    scrape_all,
    time_label,
    unplaced_venues,
    write,
)
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
        "ritz-randwick": {"name": "Ritz Randwick", "first_seen": "2026-10-16", "regions": []}
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


# --- film panel fields (B10) ---------------------------------------------------


def test_film_details_carry_poster_and_runtime_only():
    s = showing("Akira (1988)", at(LAUNCH, 19), tmdb_id=149, venue_synopsis="Venue blurb")
    details = {149: {"poster_path": "/akira.jpg", "overview": "Neo-Tokyo.", "runtime": 124}}
    data = build_data([s], None, LAUNCH)
    assert "poster_path" not in data["films"][0]
    assert build_film_details([s], data, details) == {
        "tmdb:149": {"poster_path": "/akira.jpg", "runtime": 124}
    }


def test_venue_runtime_fills_gap_and_synopsis_is_ignored():
    shows = [
        showing("Local Doco", at(LAUNCH, 18)),
        showing(
            "Local Doco", at(LAUNCH, 20), venue_synopsis="A film about Sydney.", runtime_min=81
        ),
    ]
    assert list(build_film_details(shows, build_data(shows, None, LAUNCH), {}).values()) == [
        {"runtime": 81}
    ]


def test_tmdb_runtime_beats_venue_runtime():
    s = showing("Akira", at(LAUNCH, 19), tmdb_id=149, runtime_min=125)
    details = {149: {"poster_path": None, "overview": None, "runtime": 124}}
    assert build_film_details([s], build_data([s], None, LAUNCH), details) == {
        "tmdb:149": {"runtime": 124}
    }


def test_film_details_leave_out_dropped_and_out_of_horizon_films():
    shows = [
        showing("Live Show", at(LAUNCH, 19), is_film=False, runtime_min=90),
        showing("Later", at(LAUNCH + timedelta(days=20), 19), runtime_min=90),
    ]
    assert build_film_details(shows, build_data(shows, None, LAUNCH), {}) == {}


# --- regions (B12) -------------------------------------------------------------

VENUE_INFO = {
    "ritz-randwick": {"slug": "ritz-randwick", "regions": ["East"]},
    "orpheum": {"slug": "orpheum", "regions": ["North"]},
}


def test_every_session_carries_its_venue_region():
    shows = [showing("Film", at(LAUNCH, 18)), showing("Film", at(LAUNCH, 19), venue="orpheum")]
    data = build_data(shows, None, LAUNCH, VENUE_INFO)
    assert [r["regions"] for r in data["showings"]] == [["East"], ["North"]]
    assert data["venues"]["orpheum"]["regions"] == ["North"]
    assert data["regions"] == ["East", "North"]  # REGIONS order, only those with sessions


def test_venue_missing_from_yaml_has_no_region():
    shows = [showing("Film", at(LAUNCH, 19), venue="orpheum")]
    data = build_data(shows, None, LAUNCH, {})
    assert data["showings"][0]["regions"] == [] and data["regions"] == []
    assert unplaced_venues(shows, VENUE_INFO) == []
    assert unplaced_venues(shows, {}) == ["orpheum"]


def test_venues_yaml_covers_every_scraped_venue():
    from scrapers import event, golden_age, hoyts, orpheum, palace, ritz, roseville

    slugs = {f"hoyts-{hoyts.cinema_slug(c)}" for c in hoyts.CINEMAS}
    slugs |= {f"event-{slug}" for slug in event.CINEMAS}
    slugs |= {slug for slug, _ in palace.CINEMAS.values()}
    slugs |= {m.VENUE_SLUG for m in (ritz, orpheum, golden_age, roseville)}
    venues = load_venues()
    assert {slug for slug, v in venues.items() if v.get("scraped", True)} == slugs
    assert {r for v in venues.values() for r in v["regions"]} <= set(REGIONS)
    assert all(v["lga"] for v in venues.values())


def test_east_region_cinemas():
    east = {slug for slug, v in load_venues().items() if "East" in v["regions"]}
    assert east == {
        "ritz-randwick",
        "hoyts-eastgardens",
        "hoyts-entertainment-quarter",
        "palace-moore-park",
        "event-bondi",
    }


def test_moore_park_cinemas_are_city_and_east():
    venues = load_venues()
    for slug in ("hoyts-entertainment-quarter", "palace-moore-park"):
        assert venues[slug]["regions"] == ["City", "East"]
    assert venues["ritz-randwick"]["regions"] == ["East"]


def test_cinema_in_two_regions_appears_under_both():
    info = {"ritz-randwick": {"regions": ["City", "East"]}}
    data = build_data([showing("Film", at(LAUNCH, 19))], None, LAUNCH, info)
    assert data["showings"][0]["regions"] == ["City", "East"]
    assert data["regions"] == ["City", "East"]


def test_unknown_region_rejected(tmp_path):
    path = tmp_path / "venues.yaml"
    path.write_text("- {slug: x, name: X, lga: Y, region: Westish, screens: null}\n")
    with pytest.raises(ValueError, match="Westish"):
        load_venues(path)


# --- partial days (B10d) --------------------------------------------------------

SUNDAY = date(2026, 10, 18)


def test_sunday_export_marks_thursday_onward_partial():
    # The cinema week runs Thu–Wed: on Sunday the chains have Sun–Wed in full and
    # only advance sessions from Thursday.
    shows = []
    for offset in range(14):
        day = SUNDAY + timedelta(days=offset)
        per_day = 10 if offset <= 3 else 2  # Sun, Mon, Tue, Wed in full
        shows += [showing("Film", at(day, 10 + h)) for h in range(per_day)]
    days = build_data(shows, None, SUNDAY)["days"]
    assert [d for d, v in days.items() if not v["partial"]] == [
        "2026-10-18",
        "2026-10-19",
        "2026-10-20",
        "2026-10-21",
    ]
    assert days["2026-10-22"] == {"sessions": 2, "partial": True}


def test_half_the_busiest_day_is_not_partial():
    shows = [showing("Film", at(LAUNCH, 10 + h)) for h in range(4)]
    shows += [showing("Film", at(LAUNCH + timedelta(days=1), 10 + h)) for h in range(2)]
    days = build_data(shows, None, LAUNCH)["days"]
    assert [v["partial"] for v in days.values()] == [False, False]


def test_no_showings_no_days():
    assert build_data([], None, LAUNCH)["days"] == {}


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


class FakeScraper:
    def __init__(self, name, result):
        self.__name__ = f"scrapers.{name}"
        self.result = result

    def fetch(self):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_one_failing_scraper_is_skipped(caplog):
    good = FakeScraper("ritz", [showing("Film", at(LAUNCH, 19))])
    bad = FakeScraper("event", RuntimeError("Cloudflare says no"))
    with caplog.at_level(logging.INFO, logger="export"):
        result = scrape_all([good, bad])
    assert [s.film_title for s in result] == ["Film"]
    assert "Scraper event failed" in caplog.text


def test_all_scrapers_failing_is_fatal():
    with pytest.raises(SystemExit):
        scrape_all([FakeScraper("ritz", RuntimeError("down"))])
