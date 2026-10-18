"""The page's Popular score (public/index.html, between the rank:start and rank:end
markers), run in node so the formula is tested where it lives."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

PAGE = Path(__file__).parent.parent / "public" / "index.html"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")


def scores(cases, this_year=2026):
    """Score each (film, showings) case with the page's rankScore."""
    html = PAGE.read_text()
    block = html[html.index("// rank:start") : html.index("// rank:end")]
    script = (
        block
        + f"\nconst cases = {json.dumps(cases)};"
        + f"\nconsole.log(JSON.stringify(cases.map(([f, s]) => rankScore(f, s, {this_year}))));"
    )
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def film(year, rating, votes):
    return {"year": year, "rating": rating, "vote_count": votes}


def sessions(n, venue="hoyts-broadway", type_=None):
    return [{"venue": venue, "type": type_}] * n


def test_old_film_with_one_session_beats_a_wide_middling_release():
    classic, wide = scores(
        [
            [film(1944, 7.5, 600), sessions(1, "golden-age", "retrospective")],
            [film(2026, 6.3, 1000), sessions(160)],
        ]
    )
    assert classic > wide


def test_rerelease_rule_puts_a_recent_retrospective_below_an_old_one():
    recent, old = scores(
        [
            [film(2019, 8.5, 20000), sessions(2, "palace-central", "retrospective")],
            [film(1982, 7.9, 15000), sessions(2, "palace-central", "retrospective")],
        ]
    )
    assert old > recent


def test_recent_film_not_shown_as_retrospective_keeps_its_votes():
    (rerelease, release) = scores(
        [
            [film(2019, 8.5, 20000), sessions(2, type_="retrospective")],
            [film(2019, 8.5, 20000), sessions(2, type_="new_release")],
        ]
    )
    assert release > rerelease


def test_caps_and_independent_bump():
    capped, more, indie, unknown = scores(
        [
            [film(2026, 5.0, 0), sessions(80)],
            [film(2026, 5.0, 0), sessions(200)],
            [film(2026, 5.0, 0), sessions(9, "ritz-randwick")],
            [{"year": None, "rating": None, "vote_count": None}, sessions(1)],
        ]
    )
    assert capped == pytest.approx(0.15 * 80)
    assert more == capped
    assert indie == pytest.approx(0.15 * 9 + 0.3 * 5)
    assert unknown == pytest.approx(0.15)
