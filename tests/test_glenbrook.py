from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from scrapers.glenbrook import SITE, clock, film_links, parse_film

SYDNEY = ZoneInfo("Australia/Sydney")
FIXTURES = Path(__file__).parent / "fixtures"
TODAY = date(2026, 10, 19)  # the fixtures were saved on Monday 19 October 2026
SENSE_URL = f"{SITE}/movies/sense-and-sensibility~1/"


def read(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_film_links_only_films_with_sessions_and_no_live_plays():
    links = dict(film_links(read("glenbrook_movies.html")))
    assert SENSE_URL in links
    assert f"{SITE}/movies/hadestown-the-musical/" in links
    assert f"{SITE}/movies/drummer-boy/" not in links  # "Info" only: no sessions yet
    assert not any("verdict" in url for url in links)  # Glenbrook Players: a live play
    assert len(links) == 7


def test_sessions_on_a_film_page():
    showings = parse_film(read("glenbrook_sense_and_sensibility.html"), TODAY, url=SENSE_URL)
    assert len(showings) == 11
    first = showings[0]
    assert first.start == datetime(2026, 10, 20, 10, 30, tzinfo=SYDNEY)
    assert str(first.start.tzinfo) == "Australia/Sydney"
    assert (first.venue_slug, first.venue_name) == ("glenbrook-cinema", "Glenbrook Cinema")
    assert first.film_title == "Sense and Sensibility"
    assert first.runtime_min == 132 and first.venue_synopsis.startswith("From Focus Features")
    assert first.session_id == "59805"
    assert first.booking_url == f"{SITE}/online-booking/?session_id=59805"
    assert first.film_type is None


def test_open_captions_tag():
    showings = parse_film(read("glenbrook_sense_and_sensibility.html"), TODAY)
    captioned = [s for s in showings if s.attributes]
    assert [(s.start.day, s.attributes) for s in captioned] == [(22, ["Open Captions"])]


def test_sessions_beyond_a_week_link_to_the_film_page():
    showings = parse_film(read("glenbrook_sense_and_sensibility.html"), TODAY, url=SENSE_URL)
    later = [s for s in showings if s.start.day in (27, 28)]
    assert later and all(s.booking_url == SENSE_URL and s.session_id is None for s in later)


def test_special_event_type_and_price_dropped():
    showings = parse_film(read("glenbrook_hadestown.html"), TODAY)
    assert [s.start.date() for s in showings] == [date(2026, 10, 31), date(2026, 11, 8)]
    assert all(s.film_type == "special" and s.attributes == [] for s in showings)


def test_labels_set_type():
    page = read("glenbrook_sense_and_sensibility.html")
    assert (
        parse_film(page, TODAY, "Pan's Labyrinth 2007 3 Nov 20th Anniversary")[0].film_type
        == "retrospective"
    )
    assert parse_film(page, TODAY, "Doctor Who 23 Nov One Night Only")[0].film_type == "special"


def test_clock():
    assert [clock(t) for t in ("2:00pm", "10:30am", "12:15pm", "12:05am", "Finishes")] == [
        time(14, 0),
        time(10, 30),
        time(12, 15),
        time(0, 5),
        None,
    ]
