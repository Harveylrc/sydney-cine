from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from models import Showing
from scrapers.ritz import parse_day

SYDNEY = ZoneInfo("Australia/Sydney")
FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE = FIXTURES / "ritz_2026-10-16.html"
DAY = date(2026, 10, 16)
JIFF_DAY = date(2026, 10, 24)  # Jewish International Film Festival sessions


@pytest.fixture(scope="module")
def showings():
    return parse_day(FIXTURE.read_text(encoding="utf-8"), DAY)


@pytest.fixture(scope="module")
def jiff_showings():
    return parse_day((FIXTURES / "ritz_2026-10-24.html").read_text(encoding="utf-8"), JIFF_DAY)


def showing(title, hour, minute, session_id, attributes=(), film_type=None, day=DAY):
    return Showing(
        venue_slug="ritz-randwick",
        venue_name="Ritz Randwick",
        film_title=title,
        start=datetime.combine(day, time(hour, minute), tzinfo=SYDNEY),
        session_id=session_id,
        booking_url=f"https://www.ritzcinemas.com.au/tickets?c=0000000004&s={session_id}",
        attributes=list(attributes),
        film_type=film_type,
    )


def session_page(time, tags="", genre="Drama,New Release"):
    """A one-film, one-session page in the Ritz's markup."""
    return f"""
    <div class="Markup Movie"><span class="Title"><a>Test Film</a></span>
      <a class="Link sessions-link" data-genre="{genre}" href="/tickets?c=0000000004&s=1">
        <span class="Time">{time}</span><span class="Attribute">{tags}</span>
      </a>
    </div>"""


def test_counts(showings):
    assert len(showings) == 40
    assert len({s.film_title for s in showings}) == 22
    assert len({s.session_id for s in showings}) == 40


def test_all_on_requested_day_in_sydney(showings):
    assert all(s.start.date() == DAY and s.start.tzinfo is SYDNEY for s in showings)


@pytest.mark.parametrize(
    "expected",
    [
        showing("La Bola Negra", 13, 0, "92920", ["NFT"], "new_release"),
        showing("Verity", 10, 20, "93139", film_type="new_release"),
        showing(
            "35mm Léon: The Professional (1994)",
            20,
            0,
            "78345",
            ["35MM", "RETRO"],
            "retrospective",
        ),
        showing(
            "Labyrinth – 40th Anniversary Live Show & Screening",
            19,
            30,
            "86637",
            ["LiveMusic"],
            "retrospective",
        ),
        showing("Ranabaali", 7, 0, "92974"),
    ],
    ids=lambda s: s.film_title,
)
def test_expected_showings(showings, expected):
    assert expected in showings


def test_film_types(showings):
    counts = {}
    for s in showings:
        counts[s.film_type] = counts.get(s.film_type, 0) + 1
    assert counts == {"new_release": 37, "retrospective": 2, None: 1}


def test_jiff_day_film_types(jiff_showings):
    assert len(jiff_showings) == 17
    jiff = [s for s in jiff_showings if s.film_title.startswith("JIFF:")]
    assert len(jiff) == 10
    assert all(s.film_type == "festival" for s in jiff)
    others = [s for s in jiff_showings if s not in jiff]
    assert all(s.film_type == "new_release" for s in others)


@pytest.mark.parametrize(
    "expected",
    [
        # Labelled "New Release" by the Ritz, but the JIFF tag wins.
        showing("JIFF: For The Love of a Woman", 18, 0, "89114", ["JIFF"], "festival", JIFF_DAY),
        showing(
            "JIFF: The Producers (1967)",
            16,
            0,
            "89113",
            ["JIFF", "RETRO"],
            "festival",
            JIFF_DAY,
        ),
        # THEATRE tag, but the Ritz's own "New Release" label wins over tags.
        showing(
            "Fallen Angels by Noël Coward", 13, 0, "89063", ["THEATRE"], "new_release", JIFF_DAY
        ),
    ],
    ids=lambda s: s.film_title,
)
def test_expected_jiff_day_showings(jiff_showings, expected):
    assert expected in jiff_showings


def test_comma_joined_tags_split(showings):
    qa = [s for s in showings if "Q&A" in s.attributes]
    assert len(qa) == 1 and qa[0].attributes == ["NFT", "Q&A"]


def test_no_transient_tags(showings):
    assert not any("Selling Fast" in s.attributes for s in showings)


def test_transient_tags_dropped_case_insensitively():
    [s] = parse_day(session_page("7:00 pm", "35MM, SOLD OUT, Last Chance"), DAY)
    assert s.attributes == ["35MM"]


@pytest.mark.parametrize(
    "time, expected",
    [
        ("12:15 am", datetime(2026, 10, 17, 0, 15, tzinfo=SYDNEY)),
        ("4:59 am", datetime(2026, 10, 17, 4, 59, tzinfo=SYDNEY)),
        ("5:00 am", datetime(2026, 10, 16, 5, 0, tzinfo=SYDNEY)),
        ("11:45 pm", datetime(2026, 10, 16, 23, 45, tzinfo=SYDNEY)),
    ],
)
def test_post_midnight_rolls_to_next_day(time, expected):
    [s] = parse_day(session_page(time), DAY)
    assert s.start == expected


@pytest.mark.parametrize(
    "tags, genre, expected",
    [
        ("JIFF", "Drama,New Release", "festival"),  # festival tag beats the label
        ("JIFF, RETRO", "Comedy,Retrospective", "festival"),
        ("SFF", "Drama", "festival"),
        ("", "Drama,Film Festival", "festival"),
        ("LiveMusic", "Fantasy,Retrospective", "retrospective"),  # label beats tags
        ("THEATRE", "Comedy,New Release", "new_release"),
        ("RETRO", "Drama", "retrospective"),  # no label: tags decide
        ("SPECEVENT", "Drama", "special"),
        ("LiveMusic", "Drama", "special"),
        ("STAGE", "Drama", "special"),
        ("THEATRE", "Drama", "special"),
        ("NFT, Q&A", "Drama", None),  # no signal at all
    ],
)
def test_film_type_precedence(tags, genre, expected):
    [s] = parse_day(session_page("7:00 pm", tags, genre=genre), DAY)
    assert s.film_type == expected


def test_empty_page():
    assert parse_day("<html><body></body></html>", DAY) == []


def test_sold_out_session_without_link():
    """2026-11-06: a sold-out session's link has no href (data-id still holds the
    session id). On 2026-11-02 one such link failed the whole venue."""
    html = (FIXTURES / "ritz_2026-11-06.html").read_text(encoding="utf-8")
    found = parse_day(html, date(2026, 11, 6))
    assert len(found) == 3
    sold_out = [s for s in found if s.film_title == "Zombucha!"]
    assert [(s.session_id, s.booking_url, s.start.time(), s.attributes) for s in sold_out] == [
        ("92445", None, time(18, 30), ["NFT", "Q&A"])
    ]
    linked = [s for s in found if s.booking_url]
    assert len(linked) == 2
    assert all(s.booking_url.endswith(f"s={s.session_id}") for s in linked)
