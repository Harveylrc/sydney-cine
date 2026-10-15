from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from models import Showing

SYDNEY = ZoneInfo("Australia/Sydney")


def make(**overrides):
    fields = dict(
        venue_slug="ritz-randwick",
        venue_name="Ritz Randwick",
        film_title="Paris, Texas",
        start=datetime(2026, 10, 20, 19, 30, tzinfo=SYDNEY),
    )
    return Showing(**(fields | overrides))


def test_scraped_fields():
    s = make(session_id="123", booking_url="https://example.com/book/123", attributes=["Retro"])
    assert s.session_id == "123"
    assert s.attributes == ["Retro"]


def test_optional_fields_default_empty():
    s = make()
    assert s.session_id is None
    assert s.booking_url is None
    assert s.attributes == []
    assert s.film_type is None
    assert s.vista_movie_id is None
    assert (s.tmdb_id, s.year, s.director, s.rating) == (None, None, None, None)


def test_attributes_not_shared_between_instances():
    a, b = make(), make()
    assert a.attributes is not b.attributes


def test_showing_is_immutable():
    s = make()
    with pytest.raises(AttributeError):
        s.film_title = "Kagemusha"


def test_naive_start_rejected():
    with pytest.raises(ValueError):
        make(start=datetime(2026, 10, 20, 19, 30))


def test_non_sydney_start_rejected():
    with pytest.raises(ValueError):
        make(start=datetime(2026, 10, 20, 8, 30, tzinfo=ZoneInfo("UTC")))


def test_film_type_accepted():
    assert make(film_type="retrospective").film_type == "retrospective"


def test_unknown_film_type_rejected():
    with pytest.raises(ValueError):
        make(film_type="Retrospective")
