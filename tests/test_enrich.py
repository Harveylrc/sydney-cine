import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from enrich import OVERRIDES_PATH, Cache, Match, TMDBClient, enrich, load_overrides, search_terms
from models import Showing

SYDNEY = ZoneInfo("Australia/Sydney")

LEON = {
    "id": 101,
    "title": "Léon: The Professional",
    "original_title": "Léon",
    "release_date": "1994-09-14",
    "vote_average": 8.3,
    "vote_count": 15000,
    "credits": {
        "crew": [
            {"job": "Director", "name": "Luc Besson"},
            {"job": "Producer", "name": "Patrice Ledoux"},
        ]
    },
}
FANTASTIC_BEASTS = {
    "id": 259316,
    "title": "Fantastic Beasts and Where to Find Them",
    "original_title": "Fantastic Beasts and Where to Find Them",
    "release_date": "2016-11-16",
}
WHERE_TO = {
    "id": 1342322,
    "title": "Where To?",
    "original_title": "Where To?",
    "release_date": "2024-05-01",
    "vote_average": 0.0,
    "vote_count": 0,
    "credits": {"crew": []},
}
PRODUCERS_2005 = {"id": 9899, "title": "The Producers", "release_date": "2005-12-16"}
PRODUCERS_1968 = {
    "id": 30197,
    "title": "The Producers",
    "original_title": "The Producers",
    "release_date": "1968-03-18",
    "vote_average": 7.2,
    "vote_count": 943,
    "credits": {"crew": [{"job": "Director", "name": "Mel Brooks"}]},
}
CO_DIRECTED = {
    "id": 202,
    "title": "La Bola Negra",
    "original_title": "La bola negra",
    "release_date": "2026-09-01",
    "vote_average": 7.1,
    "vote_count": 40,
    "credits": {
        "crew": [
            {"job": "Director", "name": "Anna One"},
            {"job": "Director", "name": "Ben Two"},
        ]
    },
}


class FakeResponse:
    def __init__(self, data, status=200, headers=None):
        self.data, self.status_code, self.headers = data, status, headers or {}

    def json(self):
        return self.data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeTMDB:
    """Stands in for requests.Session: answers TMDB paths from canned data."""

    def __init__(self, search=None, movies=None):
        self.headers = {}
        self.search = search or {}  # query -> list of search results (dicts)
        self.movies = movies or {}  # id -> movie details
        self.calls = []
        self.throttle_next = False

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        if self.throttle_next:
            self.throttle_next = False
            return FakeResponse({}, status=429, headers={"Retry-After": "0"})
        path = url.removeprefix("https://api.themoviedb.org/3")
        if path == "/search/movie":
            return FakeResponse({"results": self.search.get(params["query"], [])})
        return FakeResponse(self.movies[int(path.removeprefix("/movie/"))])

    def searches(self):
        return [params for url, params in self.calls if url.endswith("/search/movie")]


@pytest.fixture
def tmdb():
    return FakeTMDB(
        search={
            "Léon: The Professional": [LEON],
            "La Bola Negra": [CO_DIRECTED],
            "Where To?": [FANTASTIC_BEASTS, WHERE_TO],
            "The Producers": [PRODUCERS_2005, PRODUCERS_1968],
        },
        movies={m["id"]: m for m in (LEON, CO_DIRECTED, WHERE_TO, PRODUCERS_1968)},
    )


@pytest.fixture
def cache(tmp_path):
    return Cache(tmp_path / "tmdb.sqlite")


def run(showings, tmdb, cache, overrides=None):
    client = TMDBClient("token", session=tmdb, this_year=2026)
    return enrich(showings, client, cache, overrides)


def showing(title, vista_movie_id=None, hour=19, film_type=None):
    return Showing(
        venue_slug="ritz-randwick",
        venue_name="Ritz Randwick",
        film_title=title,
        start=datetime(2026, 10, 16, hour, 0, tzinfo=SYDNEY),
        vista_movie_id=vista_movie_id,
        film_type=film_type,
    )


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("35mm Léon: The Professional (1994)", ("Léon: The Professional", 1994)),
        ("JIFF: The Producers (1967)", ("The Producers", 1967)),
        ("35mm La Bola Negra", ("La Bola Negra", None)),
        ("The Odyssey - Digital", ("The Odyssey", None)),
        ("Paris, Texas", ("Paris, Texas", None)),
    ],
)
def test_search_terms(raw, expected):
    assert search_terms(raw) == expected


def test_title_match_fills_fields(tmdb, cache):
    [s] = run([showing("35mm Léon: The Professional (1994)")], tmdb, cache)
    assert (s.tmdb_id, s.year, s.director, s.rating) == (101, 1994, "Luc Besson", 8.3)
    assert s.film_title == "35mm Léon: The Professional (1994)"  # venue title kept
    assert tmdb.searches() == [{"query": "Léon: The Professional", "include_adult": "false"}]


def test_bearer_token_sent(tmdb, cache):
    run([showing("La Bola Negra")], tmdb, cache)
    assert tmdb.headers["Authorization"] == "Bearer token"


def test_multiple_directors_joined(tmdb, cache):
    [s] = run([showing("La Bola Negra")], tmdb, cache)
    assert s.director == "Anna One, Ben Two"


def test_each_title_queried_once_per_run(tmdb, cache):
    out = run([showing("La Bola Negra", hour=h) for h in (13, 16, 19)], tmdb, cache)
    assert [s.tmdb_id for s in out] == [202, 202, 202]
    assert len(tmdb.searches()) == 1


def test_cache_persists_across_runs(tmdb, tmp_path):
    run([showing("La Bola Negra")], tmdb, Cache(tmp_path / "db.sqlite"))
    tmdb.calls.clear()
    [s] = run([showing("35mm La Bola Negra")], tmdb, Cache(tmp_path / "db.sqlite"))
    assert s.tmdb_id == 202
    assert tmdb.calls == []


def test_vista_id_shared_across_venue_titles(tmdb, cache):
    out = run(
        [
            showing("Léon: The Professional", vista_movie_id="HO00001234"),
            showing("LEON - THE PROFESSIONAL (MA15+)", vista_movie_id="HO00001234"),
        ],
        tmdb,
        cache,
    )
    assert [s.tmdb_id for s in out] == [101, 101]
    assert len(tmdb.searches()) == 1


def test_unmatched_logged_and_kept(tmdb, cache, caplog):
    labyrinth = showing("Labyrinth – 40th Anniversary Live Show & Screening")
    with caplog.at_level(logging.WARNING, logger="enrich"):
        out = run([labyrinth, showing("La Bola Negra")], tmdb, cache)
    assert out[0] == labyrinth
    assert out[1].tmdb_id == 202
    assert "Labyrinth – 40th Anniversary" in caplog.text


def test_misses_cached_too(tmdb, cache):
    run([showing("Unknown Film")], tmdb, cache)
    run([showing("Unknown Film")], tmdb, cache)
    assert len(tmdb.searches()) == 1
    assert cache.get("title:unknown film|") == Match(tmdb_id=None)


def test_retries_after_429(tmdb, cache):
    tmdb.throttle_next = True
    [s] = run([showing("La Bola Negra")], tmdb, cache)
    assert s.tmdb_id == 202
    assert len(tmdb.searches()) == 2


def test_popular_but_different_title_rejected(tmdb, cache):
    # TMDB ranks Fantastic Beasts first for "Where To?"; only the exact title counts.
    [s] = run([showing("JIFF: Where To?")], tmdb, cache)
    assert s.tmdb_id == 1342322


def test_venue_year_within_one_of_tmdb(tmdb, cache):
    # The Ritz says 1967 (premiere); TMDB dates it 1968. The 2005 remake must not win.
    [s] = run([showing("JIFF: The Producers (1967)")], tmdb, cache)
    assert (s.tmdb_id, s.year, s.director) == (30197, 1968, "Mel Brooks")


def test_year_too_far_rejected(tmdb, cache):
    [s] = run([showing("The Producers (1990)")], tmdb, cache)
    assert s.tmdb_id is None


def test_no_title_match_is_a_miss():
    tmdb = FakeTMDB(search={"The Sea": [FANTASTIC_BEASTS]})
    assert TMDBClient("token", session=tmdb).find("The Sea", None) == Match(tmdb_id=None)


def test_unrated_film_has_no_rating(tmdb, cache):
    [s] = run([showing("JIFF: Where To?")], tmdb, cache)
    assert s.rating is None


def test_accents_ignored_in_title_match():
    resistance = {
        "id": 1165366,
        "title": "De Gaulle: Résistance",
        "release_date": "2026-06-01",
        "vote_average": 7.8,
        "vote_count": 12,
        "credits": {"crew": [{"job": "Director", "name": "Antonin Baudry"}]},
    }
    tmdb = FakeTMDB(search={"De Gaulle: Resistance": [resistance]}, movies={1165366: resistance})
    assert TMDBClient("token", session=tmdb).find("De Gaulle: Resistance", None).tmdb_id == 1165366


# --- B3b: no-year tiebreak and overrides --------------------------------------

BARBARA_WALTERS = {
    "id": 1309019,
    "title": "Barbara Walters: Tell Me Everything",
    "release_date": "2025-03-21",
}
TELL_ME_UNDATED = {
    "id": 1485945,
    "title": "Tell Me Everything",
    "original_title": "Tell Me Everything",
    "release_date": "",
    "vote_count": 0,
    "credits": {"crew": [{"job": "Director", "name": "Jeremy Chevillotte"}]},
}
TELL_ME_2026 = {
    "id": 1404400,
    "title": "Tell Me Everything",
    "original_title": "עצמאות",
    "release_date": "2026-02-01",
    "vote_average": 7.0,
    "vote_count": 3,
    "credits": {"crew": [{"job": "Director", "name": "Israeli Director"}]},
}
SEA_1978 = {
    "id": 1749174,
    "title": "The Sea",
    "release_date": "1978-01-01",
    "vote_count": 0,
    "credits": {"crew": [{"job": "Director", "name": "Jane Howell"}]},
}
THREE_COLORS_WHITE = {
    "id": 109,
    "title": "Three Colors: White",
    "release_date": "1994-01-26",
    "vote_average": 7.4,
    "vote_count": 1800,
    "credits": {"crew": [{"job": "Director", "name": "Krzysztof Kieślowski"}]},
}


@pytest.fixture
def tmdb_b3b():
    return FakeTMDB(
        search={
            "Tell Me Everything": [BARBARA_WALTERS, TELL_ME_UNDATED, TELL_ME_2026],
            "The Sea": [SEA_1978],
        },
        movies={m["id"]: m for m in (TELL_ME_UNDATED, TELL_ME_2026, SEA_1978, THREE_COLORS_WHITE)},
    )


def test_festival_showing_prefers_recent_exact_match(tmdb_b3b, cache):
    [s] = run([showing("JIFF: Tell Me Everything", film_type="festival")], tmdb_b3b, cache)
    assert (s.tmdb_id, s.year) == (1404400, 2026)


def test_new_release_showing_prefers_recent_exact_match(tmdb_b3b, cache):
    [s] = run([showing("Tell Me Everything", film_type="new_release")], tmdb_b3b, cache)
    assert s.tmdb_id == 1404400


def test_retrospective_showing_keeps_first_exact_match(tmdb_b3b, cache):
    [s] = run([showing("Tell Me Everything", film_type="retrospective")], tmdb_b3b, cache)
    assert s.tmdb_id == 1485945


def test_untyped_showing_keeps_first_exact_match(tmdb_b3b, cache):
    [s] = run([showing("Tell Me Everything")], tmdb_b3b, cache)
    assert s.tmdb_id == 1485945


def test_festival_and_retrospective_same_title_resolved_separately(tmdb_b3b, cache):
    out = run(
        [
            showing("JIFF: Tell Me Everything", film_type="festival"),
            showing("Tell Me Everything", film_type="retrospective"),
        ],
        tmdb_b3b,
        cache,
    )
    assert [s.tmdb_id for s in out] == [1404400, 1485945]


def test_no_recent_candidate_falls_back_to_first_exact(tmdb_b3b, cache):
    [s] = run([showing("JIFF: The Sea", film_type="festival")], tmdb_b3b, cache)
    assert s.tmdb_id == 1749174


def test_recent_cutoff_is_three_years():
    old = {"id": 1, "title": "Same", "release_date": "2022-12-31"}
    edge = {"id": 2, "title": "Same", "release_date": "2023-01-01", "credits": {"crew": []}}
    tmdb = FakeTMDB(search={"Same": [old, edge]}, movies={2: edge})
    client = TMDBClient("token", session=tmdb, this_year=2026)
    assert client.find("Same", None, prefer_recent=True).tmdb_id == 2


def test_venue_year_beats_recent_preference(tmdb, cache):
    # A year in the title governs; the recent tiebreak only applies without one.
    [s] = run([showing("JIFF: The Producers (1967)", film_type="festival")], tmdb, cache)
    assert s.tmdb_id == 30197


def test_override_id_wins_over_search(tmdb_b3b, cache):
    title = "Three Colours: White (1994)"
    [s] = run([showing(title)], tmdb_b3b, cache, overrides={title: 109})
    assert (s.tmdb_id, s.year, s.director) == (109, 1994, "Krzysztof Kieślowski")
    assert tmdb_b3b.searches() == []


def test_override_lookup_cached(tmdb_b3b, cache):
    title = "Three Colours: White (1994)"
    run([showing(title)], tmdb_b3b, cache, overrides={title: 109})
    tmdb_b3b.calls.clear()
    run([showing(title)], tmdb_b3b, cache, overrides={title: 109})
    assert tmdb_b3b.calls == []


def test_override_none_is_unmatched_and_not_logged(tmdb_b3b, cache, caplog):
    sea = showing("JIFF: The Sea", film_type="festival")
    with caplog.at_level(logging.WARNING, logger="enrich"):
        [s] = run([sea], tmdb_b3b, cache, overrides={"JIFF: The Sea": None})
    assert s == sea
    assert tmdb_b3b.calls == []
    assert caplog.text == ""


def test_override_matches_exact_venue_title_only(tmdb_b3b, cache):
    out = run(
        [showing("JIFF: The Sea"), showing("The Sea")],
        tmdb_b3b,
        cache,
        overrides={"JIFF: The Sea": None},
    )
    assert [s.tmdb_id for s in out] == [None, 1749174]


def test_load_overrides(tmp_path):
    path = tmp_path / "overrides.csv"
    path.write_text(
        'venue_title,tmdb_id\nThree Colours: White (1994),109\n"Paris, Texas",655\nThe Sea,none\n',
        encoding="utf-8",
    )
    assert load_overrides(path) == {
        "Three Colours: White (1994)": 109,
        "Paris, Texas": 655,
        "The Sea": None,
    }


def test_load_overrides_missing_file(tmp_path):
    assert load_overrides(tmp_path / "nope.csv") == {}


def test_seeded_overrides_file():
    assert load_overrides(OVERRIDES_PATH) == {
        "Three Colours: White (1994)": 109,
        "JIFF: For The Love of a Woman": 1143204,
        "JIFF: Dust Bowls and Jewish Souls": 1660550,
        "JIFF: The Wedding Entertainer (The Tale of Moishe Badhan)": 1573783,
        "JIFF: The Sea": None,
    }
