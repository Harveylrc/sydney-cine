import dataclasses
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from models import Showing

SYDNEY = ZoneInfo("Australia/Sydney")


def test_showing_holds_fields():
    s = Showing(
        venue="Ritz Randwick",
        title="Paris, Texas",
        starts_at=datetime(2026, 10, 20, 19, 30, tzinfo=SYDNEY),
        booking_url="https://example.com/book/1",
    )
    assert s.venue == "Ritz Randwick"
    assert s.starts_at.tzinfo is SYDNEY


def test_booking_url_optional():
    s = Showing("Hayden Orpheum", "Stalker", datetime(2026, 10, 21, 18, 0, tzinfo=SYDNEY))
    assert s.booking_url is None


def test_showing_is_immutable():
    s = Showing("Chauvel", "Ran", datetime(2026, 10, 22, 20, 0, tzinfo=SYDNEY))
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.title = "Kagemusha"
