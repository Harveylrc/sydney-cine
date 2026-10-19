import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import requests

from scrapers import reading

SYDNEY = ZoneInfo("Australia/Sydney")
FIXTURE = Path(__file__).parent / "fixtures" / "reading_films.json"  # from the 19 Oct VPN run
PAYLOAD = json.loads(FIXTURE.read_text(encoding="utf-8"))


def by_title(title):
    return [s for s in reading.parse(PAYLOAD) if s.film_title == title]


def test_sessions_for_each_cinema():
    showings = reading.parse(PAYLOAD)
    assert {s.venue_slug for s in showings} == {
        "reading-rhodes",
        "reading-auburn",
        "reading-rouse-hill",
    }
    assert {s.venue_name for s in showings} >= {"Reading Rouse Hill"}
    assert all(str(s.start.tzinfo) == "Australia/Sydney" for s in showings)


def test_session_fields():
    first = by_title("Spider-Man: Brand New Day")[0]
    assert first.start == datetime(2026, 10, 19, 20, 30, tzinfo=SYDNEY)
    assert first.session_id == "108096" and first.vista_movie_id == "HO00004445"
    assert first.venue_director == "Destin Daniel Cretton" and first.runtime_min == 145
    assert (
        first.venue_synopsis.startswith("After the record-breaking")
        and "<p>" not in first.venue_synopsis
    )
    assert first.booking_url == "https://readingcinemas.com.au/rhodes"
    assert first.attributes == [] and first.film_type is None


def test_rouse_hill_links_with_readings_own_id():
    [hill] = [s for s in reading.parse(PAYLOAD) if s.venue_slug == "reading-rouse-hill"][:1]
    assert hill.booking_url == "https://readingcinemas.com.au/rousehill"


def test_series_prefix_typed_and_tagged():
    [taxi, _] = by_title("Taxi Driver (1976)")
    assert taxi.film_type == "retrospective" and taxi.attributes == ["Reading Rewind"]
    [trek, _] = by_title("Star Trek: The Motion Picture (1979)")
    assert trek.attributes == ["Reading Rewind", "Director's Cut"]
    [hunger] = by_title("The Hunger Games: Sunrise on the Reaping")
    assert hunger.film_type == "special" and hunger.attributes == ["Tributes Night", "TitanLuxe"]


def test_real_dash_in_title_kept():
    assert by_title("Paw Patrol - The Dino Movie")


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Reading Rewind - 9 to 5 (1981)", ("9 to 5 (1981)", "retrospective", ["Reading Rewind"])),
        ("Go For Broke 2 (Mandarin)", ("Go For Broke 2 (Mandarin)", None, [])),
        ("Mr. &amp; Mrs. Pardon", ("Mr. & Mrs. Pardon", None, [])),
    ],
)
def test_clean_title(name, expected):
    assert reading.clean_title(name) == expected


def test_trim_keeps_only_what_we_read():
    shown = {"id": "1", "ScheduledFilmId": "HO1", "date_time": "2026-10-19T10:00:00+11:00"}
    showtimes = [
        dict(shown, availableSeats="9", enabled=True),
        {"id": "2", "ScheduledFilmId": "HO1", "date_time": "2026-10-19T12:00", "enabled": False},
    ]
    showtype = {"type": "Standard", "amenities": ["a"], "showtimes": showtimes}
    film = {
        "name": "X",
        "director": "D",
        "length": "90",
        "cast": "lots",
        "showdates": [{"date": "2026-10-19", "showtypes": [showtype]}],
    }
    [trimmed] = reading.trim([film])
    assert "cast" not in trimmed
    assert trimmed["showdates"][0]["showtypes"][0]["showtimes"] == [shown]


def test_saved_copy_used_when_under_eight_days(tmp_path):
    path = tmp_path / "reading-latest.json"
    reading.save_latest(PAYLOAD, path)
    fetched = datetime.fromisoformat(PAYLOAD["fetched"])
    assert reading.load_latest(path, fetched + timedelta(days=7)) == PAYLOAD
    assert reading.load_latest(path, fetched + timedelta(days=9)) is None
    assert reading.load_latest(tmp_path / "missing.json") is None


def test_fetch_falls_back_when_the_api_refuses(monkeypatch, tmp_path):
    def refused(self):
        raise requests.HTTPError("403 Forbidden")

    path = tmp_path / "reading-latest.json"
    reading.save_latest(dict(PAYLOAD, fetched=datetime.now(SYDNEY).isoformat()), path)
    monkeypatch.setattr(reading.ReadingScraper, "fetch_live", refused)
    monkeypatch.setattr(reading, "LATEST", path)
    monkeypatch.setattr(reading, "load_latest", lambda: reading.json.loads(path.read_text()))
    assert len(reading.fetch()) == len(reading.parse(PAYLOAD))


def test_settings_response_never_saved(tmp_path):
    scraper = reading.ReadingScraper(cache_dir=tmp_path)
    scraper._save("prod-api.readingcinemas.com.au", f"{reading.API}/settings/1", b"token")
    scraper._save("prod-api.readingcinemas.com.au", f"{reading.API}/films", b"films")
    assert [p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()] == [b"films"]
