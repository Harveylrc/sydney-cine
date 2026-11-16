"""The page's sort order (public/index.html, between the sort:start and sort:end
markers), run in node so it is tested where it lives."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

PAGE = Path(__file__).parent.parent / "public" / "index.html"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")


def order(films, sort="popular", reversed_=False):
    """Titles in the order the page's comparer puts the films."""
    html = PAGE.read_text()
    block = html[html.index("// sort:start") : html.index("// sort:end")]
    script = (
        block
        + f"\nconst films = {json.dumps(films)};"
        + f"\nfilms.sort(comparer({json.dumps(sort)}, {json.dumps(reversed_)}));"
        + "\nconsole.log(JSON.stringify(films.map((o) => o.film.title)));"
    )
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def film(title, venues, votes=0):
    """A film with one session at each venue listed."""
    return {
        "film": {"title": title, "vote_count": votes},
        "showings": [{"venue": v} for v in venues],
    }


def test_popular_sessions_come_first():
    films = [film("Few", ["a"], votes=9999), film("Many", ["a", "a", "a"])]
    assert order(films) == ["Many", "Few"]
    assert order(films, reversed_=True) == ["Few", "Many"]


def test_popular_tie_goes_to_more_cinemas():
    films = [film("One cinema", ["a", "a"], votes=9999), film("Two cinemas", ["a", "b"])]
    assert order(films) == ["Two cinemas", "One cinema"]
    assert order(films, reversed_=True) == ["One cinema", "Two cinemas"]


def test_popular_then_tmdb_votes():
    films = [film("Obscure", ["a"], votes=10), film("Known", ["b"], votes=5000)]
    assert order(films) == ["Known", "Obscure"]
    assert order(films, reversed_=True) == ["Obscure", "Known"]


def test_popular_full_ties_stay_a_to_z_both_ways():
    films = [film("Beta", ["a"], votes=5), film("Alpha", ["b"], votes=5)]
    assert order(films) == ["Alpha", "Beta"]
    assert order(films, reversed_=True) == ["Alpha", "Beta"]


def test_missing_votes_count_as_none():
    films = [
        film("Voted", ["a"], votes=1),
        {"film": {"title": "Unmatched"}, "showings": [{"venue": "b"}]},
    ]
    assert order(films) == ["Voted", "Unmatched"]


def test_release_date_keeps_undated_films_last_both_ways():
    films = [
        {"film": {"title": "Undated", "year": None}, "showings": []},
        {"film": {"title": "Old", "year": 1950}, "showings": []},
        {"film": {"title": "New", "year": 2026}, "showings": []},
    ]
    assert order(films, "year") == ["New", "Old", "Undated"]
    assert order(films, "year", True) == ["Old", "New", "Undated"]
