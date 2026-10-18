import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from scrapers.palace import attributes, film_type, parse_page, runtime, start_time

SYDNEY = ZoneInfo("Australia/Sydney")
FIXTURE = Path(__file__).parent / "fixtures" / "palace_central_2026-10-18.html"


@pytest.fixture(scope="module")
def showings():
    return parse_page(FIXTURE.read_text(encoding="utf-8"))


def by_id(showings, session_id):
    return next(s for s in showings if s.session_id == session_id)


def session(info=(), display=None, platinum=False):
    return {"sessionInfo": list(info), "displayAttributeText": display, "isPlatinum": platinum}


# --- the saved Palace Central page --------------------------------------------


def test_fixture_counts(showings):
    assert len(showings) == 526
    assert len({s.film_title for s in showings}) == 107
    assert {(s.venue_slug, s.venue_name) for s in showings} == {
        ("palace-central", "Palace Central")
    }


def test_fixture_session(showings):
    s = by_id(showings, "178738")
    assert s.film_title == "Sense and Sensibility"
    # "2026-10-19T12:30:00.000Z" is 12:30 in Sydney, not 12:30 UTC
    assert s.start == datetime(2026, 10, 19, 12, 30, tzinfo=SYDNEY)
    assert s.booking_url == "https://buy.palacecinemas.com.au/?cinema=200&session=178738"
    assert s.attributes == ["Audio Description", "Closed Captions", "NFT"]
    assert s.vista_movie_id == "HO00019390"
    assert s.runtime_min == 131
    assert s.venue_synopsis is None  # synopses were emptied in the trimmed fixture
    assert s.film_type is None


def test_fixture_film_types(showings):
    assert by_id(showings, "178524").film_type == "festival"  # BFF26 Hamlet
    assert by_id(showings, "177215").film_type == "retrospective"  # La La Land, genre
    assert by_id(showings, "173759").film_type == "special"  # Royal Ballet: Swan Lake
    assert by_id(showings, "179380").attributes == ["NFT", "Movie Club"]


def test_every_start_is_sydney_time(showings):
    assert all(s.start.tzinfo == SYDNEY for s in showings)
    assert all(10 <= s.start.hour <= 21 for s in showings)


# --- pieces -------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2026-10-19T12:30:00.000Z", datetime(2026, 10, 19, 12, 30)),  # AEDT
        ("2027-06-23T12:00:00.000Z", datetime(2027, 6, 23, 12, 0)),  # AEST
    ],
)
def test_start_time(raw, expected):
    assert start_time(raw) == expected.replace(tzinfo=SYDNEY)


def test_attributes_mapped_dropped_and_kept():
    unknown = set()
    info = ["Audio Description Session", "Hearing Impaired", "No Free Tickets", "Special Event"]
    assert attributes(session(info, "INCL. Q&A"), unknown) == [
        "Audio Description",
        "NFT",
        "Special Event",
        "Q&A",
    ]
    assert attributes(session([], "RECLINER"), unknown) == []
    assert attributes(session(["Special Event"], "SPECIAL EVENT"), unknown) == ["Special Event"]
    assert attributes(session([], "SING-ALONG", platinum=True), unknown) == [
        "SING-ALONG",
        "Platinum",
    ]
    assert unknown == {"SING-ALONG"}


@pytest.mark.parametrize(
    "title, genres, labels, expected",
    [
        ("GFF26 Electra", ["Drama"], [], "festival"),
        ("Hope", ["Film Festival", "Drama"], ["Special Event"], "festival"),
        ("The Thing", ["Horror", "Retrospective"], ["Special Event"], "retrospective"),
        ("NT Live: Golden Boy", ["Theatre"], [], "special"),
        ("Scream", ["Horror"], ["Retro"], "retrospective"),
        ("Dune: Part Three", ["Sci-Fi"], ["Special Event"], "special"),
        ("Verity", ["Thriller"], [], None),
    ],
)
def test_film_type(title, genres, labels, expected):
    assert film_type({"title": title, "genreNames": genres}, labels) == expected


@pytest.mark.parametrize(
    "text, minutes", [("131 MIN", 131), ("90 min", 90), ("", None), (None, None)]
)
def test_runtime(text, minutes):
    assert runtime(text) == minutes


def test_synopsis_passed_through():
    data = {
        "props": {
            "pageProps": {
                "cinema": {"slug": "palace-norton-street"},
                "sessions": [
                    {
                        "movieId": "HO1",
                        "title": "The Fox",
                        "genreNames": [],
                        "synopsis": "  Dario Russo's dark comedy.\n ",
                        "runTime": "90 MIN",
                        "sessions": [
                            {
                                "sessionId": "1",
                                "cinemaId": "129",
                                "date": "2026-10-20T18:30:00.000Z",
                                "sessionInfo": [],
                                "displayAttributeText": None,
                            }
                        ],
                    }
                ],
            }
        }
    }
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'
    [s] = parse_page(html)
    assert s.venue_synopsis == "Dario Russo's dark comedy."
    assert s.runtime_min == 90
