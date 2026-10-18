from enrich import TMDBClient
from scripts.build_directors import build, our_directors, rank, rated_films


class FakeResponse:
    def __init__(self, data):
        self.data, self.status_code, self.headers = data, 200, {}

    def json(self):
        return self.data

    def raise_for_status(self):
        pass


class FakeTMDB:
    """discover: year -> list of pages (each a list of (id, votes)); credits: id -> directors."""

    def __init__(self, discover, credits):
        self.headers = {}
        self.discover, self.credits = discover, credits
        self.calls = []

    def get(self, url, params=None, timeout=None):
        path = url.removeprefix("https://api.themoviedb.org/3")
        self.calls.append((path, params))
        if path == "/discover/movie":
            pages = self.discover.get(params["primary_release_year"], [[]])
            results = [{"id": i, "vote_count": v} for i, v in pages[params["page"] - 1]]
            return FakeResponse({"results": results, "total_pages": len(pages)})
        tmdb_id = int(path.split("/")[2])
        crew = [{"job": "Director", "name": n} for n in self.credits[tmdb_id]]
        crew.append({"job": "Producer", "name": "Someone"})
        return FakeResponse({"crew": crew})


def client(tmdb):
    return TMDBClient("token", session=tmdb, this_year=2026)


def test_rated_films_every_year_and_page():
    tmdb = FakeTMDB({1997: [[(1, 742)], [(2, 300)]], 2026: [[(3, 5000)]]}, {})
    assert rated_films(client(tmdb), 2026) == {1: 742, 2: 300, 3: 5000}
    discover = [p for path, p in tmdb.calls if path == "/discover/movie"]
    assert discover[0]["vote_count.gte"] == 200
    assert {p["primary_release_year"] for p in discover} == set(range(1900, 2027))


def test_discover_stops_at_page_500():
    pages = [[(i, 200)] for i in range(600)]
    tmdb = FakeTMDB({2000: pages}, {})
    assert len(rated_films(client(tmdb), 2000)) == 500


def test_rank_by_total_votes_then_name():
    films = {1: 742, 2: 900, 3: 500, 4: 100}
    credits = {1: ["Abbas Kiarostami"], 2: ["B"], 3: ["Abbas Kiarostami", "A"], 4: ["A"]}
    assert rank(films, credits) == ["Abbas Kiarostami", "B", "A"]
    assert rank(films, credits, keep=1) == ["Abbas Kiarostami"]


def test_our_directors_split_and_deduplicated():
    data = {"films": [{"director": "Joel Coen, Ethan Coen"}, {"director": "Joel Coen"}, {}]}
    assert our_directors(data) == ["Ethan Coen", "Joel Coen"]
    assert our_directors(None) == []


def test_build_appends_our_directors_not_already_listed():
    tmdb = FakeTMDB({1997: [[(1, 742), (2, 300)]]}, {1: ["Abbas Kiarostami"], 2: ["Local Hero"]})
    data = {"films": [{"director": "Local Hero"}, {"director": "New Name"}]}
    names = build(client(tmdb), 1997, data, workers=2)
    assert names == ["Abbas Kiarostami", "Local Hero", "New Name"]
