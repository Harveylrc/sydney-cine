import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from enrich import (
    OVERRIDES_PATH,
    Cache,
    ClaudeChooser,
    Match,
    TMDBClient,
    claude_chooser,
    enrich,
    load_overrides,
    lookup_key,
    search_terms,
)
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


def showing(title, vista_movie_id=None, hour=19, film_type=None, venue="ritz-randwick"):
    return Showing(
        venue_slug=venue,
        venue_name=venue.replace("-", " ").title(),
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
        ("Ranabaali (Telugu, Eng Sub)", ("Ranabaali", None)),
        ("Godzilla Minus Zero  (Japanese, Eng Sub)", ("Godzilla Minus Zero", None)),
        ("(LFF) Liste De Marriage", ("Liste De Marriage", None)),
        ("BFF26 The Man Who Fell to Earth", ("The Man Who Fell to Earth", None)),
        ("JFF26 1ST KISS", ("1ST KISS", None)),
        ("Hitchcock Retro - Psycho 4K Restoration", ("Psycho", None)),
        ("Hitchcok Retro - Rebecca 4K Restoration", ("Rebecca", None)),
        ("JFF 2026 - Pitfall on 35mm Film", ("Pitfall", None)),
        ("Casino Royale - 20th Anniversary 4K Restoration", ("Casino Royale", None)),
        ("La La Land 10th Anniversary + Live Performance", ("La La Land", None)),
        ("GIANT – The Play Preview Event", ("GIANT – The Play", None)),
        (
            "George Michael - The Faith Tour Special Event",
            ("George Michael - The Faith Tour", None),
        ),
        ("Pressure - Preview Event", ("Pressure", None)),
        ("Highlander - Christopher Lambert Live Q&A", ("Highlander", None)),
        (
            "Two of Us - The Songs of Simon & Garfunkel Live",
            ("Two of Us - The Songs of Simon & Garfunkel Live", None),
        ),
        (
            "Ozzy & Black Sabbath - Back to the Beginning",
            ("Ozzy & Black Sabbath - Back to the Beginning", None),
        ),
        ("Avengers Endgame: Encore", ("Avengers Endgame", None)),
        (
            "Stray Kids World Tour <Run It> Live Viewing (Encore)",
            ("Stray Kids World Tour <Run It> Live Viewing", None),
        ),
        ("Rocky (1976) - 50th Anniversary", ("Rocky", 1976)),
        ("Always Yours, Never Mine (Tagalog, Eng Sub)", ("Always Yours, Never Mine", None)),
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


def test_vista_ids_are_per_chain(tmdb, cache):
    out = run(
        [
            showing("Léon: The Professional", vista_movie_id="HO00001234", venue="hoyts-broadway"),
            showing("La Bola Negra", vista_movie_id="HO00001234", venue="palace-central"),
        ],
        tmdb,
        cache,
    )
    assert [s.tmdb_id for s in out] == [101, 202]
    assert cache.get("vista:hoyts:HO00001234").tmdb_id == 101


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
        "Labyrinth – 40th Anniversary Live Show & Screening": 13597,
        "Fallen Angels by Noël Coward": 1702350,
        "JIFF: The Heroes of the Louvre": 1208117,
        "JIFF: Sapiro v. Ford: The Jew Who Sued Henry Ford": 1552128,
        "JIFF: Lansky: The Jewish Godfather": None,
        "JIFF: Who Are We: The Story of the Ajax Football Club": None,
        "Black Christmas": 16938,  # 1974, not the 2019 remake
        "BFF26 The Match": 1666712,
        "IFF26 Separate Beds": 1397055,
        "GFF26 Female": 1566262,
        "GFF26 The River": 1376339,
        "GFF26 Electra": None,  # filmed stage production, not on TMDB
    }


# --- B4b: vote_count -----------------------------------------------------------


def test_vote_count_filled(tmdb, cache):
    [s] = run([showing("35mm Léon: The Professional (1994)")], tmdb, cache)
    assert s.vote_count == 15000


def test_unrated_film_has_zero_votes_and_no_rating(tmdb, cache):
    [s] = run([showing("JIFF: Where To?")], tmdb, cache)
    assert (s.vote_count, s.rating) == (0, None)


def test_vote_count_survives_cache(tmdb, tmp_path):
    run([showing("La Bola Negra")], tmdb, Cache(tmp_path / "db.sqlite"))
    tmdb.calls.clear()
    [s] = run([showing("La Bola Negra")], tmdb, Cache(tmp_path / "db.sqlite"))
    assert s.vote_count == 40
    assert tmdb.calls == []


# --- Claude-assisted matching (B3c) -------------------------------------------

BLACK_XMAS_2019 = {
    "id": 551808,
    "title": "Black Christmas",
    "original_title": "Black Christmas",
    "release_date": "2019-12-11",
    "overview": "Sorority pledges are stalked over the Christmas break.",
    "vote_average": 5.0,
    "vote_count": 900,
    "credits": {"crew": [{"job": "Director", "name": "Sophia Takal"}]},
}
BLACK_XMAS_1974 = BLACK_XMAS_2019 | {
    "id": 16938,
    "release_date": "1974-10-11",
    "overview": "Sorority sisters receive strange phone calls.",
    "credits": {"crew": [{"job": "Director", "name": "Bob Clark"}]},
}
EL_PARTIDO = CO_DIRECTED | {
    "id": 1666712,
    "title": "The Match",
    "original_title": "El Partido",
    "overview": "Argentina vs England, 1986.",
}


class FakeClaude:
    """Stands in for anthropic.Anthropic(): replies from a list, records prompts."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []
        self.messages = self

    def create(self, **kwargs):
        self.prompts.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if not reply.lower().startswith(("answer", "thinking")) and "answer:" not in reply.lower():
            reply = f"Answer: {reply}"  # shorthand: FakeClaude("16938")

        class Block:
            def __init__(self, kind, text):
                self.type, self.text = kind, text

        class Response:
            content = [Block("thinking", "Let me compare the candidates."), Block("text", reply)]

        return Response()


@pytest.fixture
def tmdb_b3c():
    films = [BLACK_XMAS_2019, BLACK_XMAS_1974, EL_PARTIDO, LEON]
    return FakeTMDB(
        search={
            "Black Christmas": [BLACK_XMAS_2019, BLACK_XMAS_1974],
            "The Match": [EL_PARTIDO],
            "Léon: The Professional": [LEON],
            "Nothing Here": [],
        },
        movies={m["id"]: m for m in films},
    )


def run_claude(showings, tmdb, cache, claude, max_calls=200, overrides=None):
    client = TMDBClient("token", session=tmdb, this_year=2026)
    chooser = ClaudeChooser(claude, max_calls=max_calls)
    return enrich(showings, client, cache, overrides, chooser), chooser


def test_several_exact_candidates_go_to_claude(tmdb_b3c, cache):
    retro = showing("Black Christmas", film_type="retrospective")
    [s], chooser = run_claude([retro], tmdb_b3c, cache, FakeClaude("16938"))
    assert (s.tmdb_id, s.year, s.director) == (16938, 1974, "Bob Clark")
    assert chooser.calls == 1 and chooser.answers == {"matched": 1, "none": 0}


def test_prompt_carries_venue_and_candidates(tmdb_b3c, cache):
    claude = FakeClaude("16938")
    retro = showing("Black Christmas", film_type="retrospective")
    retro = Showing(**{**retro.__dict__, "attributes": ["35mm", "Q&A"]})
    run_claude([retro], tmdb_b3c, cache, claude)
    [call] = claude.prompts
    text = call["messages"][0]["content"]
    assert call["model"] == "claude-sonnet-5-5"
    assert "Title: Black Christmas" in text and "Type: retrospective" in text
    assert "Tags: 35mm, Q&A" in text
    assert "tmdb_id 551808: Black Christmas, 2019, directed by Sophia Takal" in text
    assert "tmdb_id 16938: Black Christmas, 1974, directed by Bob Clark" in text


def test_no_exact_candidate_goes_to_claude_with_all_results(tmdb_b3c, cache):
    tmdb_b3c.search["The Match"] = [EL_PARTIDO | {"title": "El Partido"}]
    claude = FakeClaude("1666712")
    [s], _ = run_claude([showing("BFF26 The Match", film_type="festival")], tmdb_b3c, cache, claude)
    assert s.tmdb_id == 1666712
    assert (
        "The Match (original title: El Partido), 2026"
        in claude.prompts[0]["messages"][0]["content"]
    )


def test_single_exact_candidate_skips_claude(tmdb_b3c, cache):
    claude = FakeClaude()
    [s], chooser = run_claude([showing("Léon: The Professional")], tmdb_b3c, cache, claude)
    assert s.tmdb_id == 101 and chooser.calls == 0


def test_no_search_results_skips_claude(tmdb_b3c, cache):
    [s], chooser = run_claude([showing("Nothing Here")], tmdb_b3c, cache, FakeClaude())
    assert s.tmdb_id is None and chooser.calls == 0


def test_override_skips_claude(tmdb_b3c, cache):
    overrides = {"Black Christmas": 16938}
    [s], chooser = run_claude(
        [showing("Black Christmas")], tmdb_b3c, cache, FakeClaude(), overrides=overrides
    )
    assert s.tmdb_id == 16938 and chooser.calls == 0


def test_claude_none_is_unmatched_and_cached(tmdb_b3c, cache):
    [s], _ = run_claude([showing("Black Christmas")], tmdb_b3c, cache, FakeClaude("none"))
    assert s.tmdb_id is None
    [s], chooser = run_claude([showing("Black Christmas")], tmdb_b3c, cache, FakeClaude())
    assert s.tmdb_id is None and chooser.calls == 0


def test_claude_answer_cached_across_runs(tmdb_b3c, cache):
    run_claude([showing("Black Christmas")], tmdb_b3c, cache, FakeClaude("16938"))
    [s], chooser = run_claude([showing("Black Christmas")], tmdb_b3c, cache, FakeClaude())
    assert s.tmdb_id == 16938 and chooser.calls == 0


def test_budget_exhausted_falls_back_to_rules_uncached(tmdb_b3c, cache, caplog):
    films = [showing("Black Christmas", film_type="retrospective"), showing("BFF26 The Match")]
    tmdb_b3c.search["The Match"] = [EL_PARTIDO | {"title": "El Partido"}]
    with caplog.at_level(logging.WARNING, logger="enrich"):
        (first, second), chooser = run_claude(
            films, tmdb_b3c, cache, FakeClaude("16938"), max_calls=1
        )
    assert first.tmdb_id == 16938
    assert second.tmdb_id is None  # rules: no exact title
    assert chooser.calls == 1 and "budget of 1 calls used" in caplog.text
    # Next run, with budget, Claude gets the one it missed.
    [s], chooser = run_claude([films[1]], tmdb_b3c, cache, FakeClaude("1666712"))
    assert s.tmdb_id == 1666712 and chooser.calls == 1


def test_answer_line_after_reasoning(tmdb_b3c, cache):
    reply = "BFF26 is a festival code. The 1974 film fits a retrospective.\n\n**Answer: 16938**"
    retro = showing("Black Christmas", film_type="retrospective")
    [s], _ = run_claude([retro], tmdb_b3c, cache, FakeClaude(reply))
    assert s.tmdb_id == 16938


@pytest.mark.parametrize(
    "reply",
    [RuntimeError("overloaded"), "thinking: the second one probably", "Answer: 999"],
)
def test_unusable_reply_falls_back_to_rules_uncached(tmdb_b3c, cache, reply):
    retro = showing("Black Christmas", film_type="retrospective")
    [s], _ = run_claude([retro], tmdb_b3c, cache, FakeClaude(reply))
    assert s.tmdb_id == 551808  # rules: TMDB's first exact match
    assert cache.get(lookup_key(retro)) is None


def test_no_api_key_means_no_chooser(tmp_path, monkeypatch, caplog):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("TMDB_API_KEY=abc\n")
    with caplog.at_level(logging.INFO, logger="enrich"):
        assert claude_chooser(env) is None
    assert caplog.text.count("ANTHROPIC_API_KEY not set") == 1


def test_api_key_read_from_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("TMDB_API_KEY=abc\nANTHROPIC_API_KEY=sk-test\n")
    assert isinstance(claude_chooser(env), ClaudeChooser)


def test_prompt_carries_venue_evidence_and_rules_choice(tmdb_b3c, cache):
    claude = FakeClaude("16938")
    retro = showing("Black Christmas", film_type="retrospective")
    retro = Showing(
        **{
            **retro.__dict__,
            "venue_synopsis": "Sorority sisters,\n  strange calls.",
            "runtime_min": 98,
        }
    )
    run_claude([retro], tmdb_b3c, cache, claude)
    text = claude.prompts[0]["messages"][0]["content"]
    assert "Running time: 98 min" in text
    assert "Venue's description: Sorority sisters, strange calls." in text
    assert "The title rules' choice: tmdb_id 551808." in text  # TMDB's first exact match
    assert "keep it unless" in claude.prompts[0]["system"]


def test_prompt_without_evidence_or_rules_choice(tmdb_b3c, cache):
    tmdb_b3c.search["The Match"] = [EL_PARTIDO | {"title": "El Partido"}]
    claude = FakeClaude("1666712")
    run_claude([showing("BFF26 The Match")], tmdb_b3c, cache, claude)
    text = claude.prompts[0]["messages"][0]["content"]
    assert "Running time" not in text and "Venue's description" not in text
    assert "The title rules' choice: no choice." in text


def test_candidate_runtime_in_prompt(tmdb_b3c, cache):
    tmdb_b3c.movies[16938] = BLACK_XMAS_1974 | {"runtime": 98}
    claude = FakeClaude("16938")
    run_claude([showing("Black Christmas")], tmdb_b3c, cache, claude)
    assert (
        "Black Christmas, 1974, 98 min, directed by Bob Clark"
        in claude.prompts[0]["messages"][0]["content"]
    )
