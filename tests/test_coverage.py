from coverage import coverage

VENUES = {
    "ritz-randwick": {"name": "Ritz Randwick", "screens": 6},
    "hoyts-broadway": {"name": "Hoyts Broadway", "screens": 12},
    "event-bondi": {"name": "Event Bondi", "screens": 8, "closed": True},
    "event-hornsby": {"name": "Event Hornsby", "screens": 9},  # scraper failed tonight
    "dendy-newtown": {"name": "Dendy Newtown", "screens": 4, "scraped": False},
    "mystery": {"name": "Mystery", "screens": None},
}


def rows(*venues):
    return [{"venue": v} for v in venues]


def test_share_of_screens_with_sessions():
    result = coverage(VENUES, rows("ritz-randwick", "hoyts-broadway", "hoyts-broadway"))
    assert result == {
        "screens_covered": 18,
        "screens_total": 31,
        "percent": 58,
        "cinemas_covered": 2,
        "cinemas_total": 4,
        "uncovered": ["Dendy Newtown", "Event Hornsby"],
        "unknown_screens": ["mystery"],
        "closed": ["Event Bondi"],
    }


def test_closed_cinema_with_sessions_again_counts():
    result = coverage(VENUES, rows("event-bondi"))
    assert result["screens_covered"] == 8 and result["closed"] == []


def test_failing_scraper_counts_as_uncovered():
    result = coverage(VENUES, rows("ritz-randwick"))
    assert result["screens_covered"] == 6 and "Hoyts Broadway" in result["uncovered"]


def test_no_screen_counts_no_percent():
    assert coverage({"x": {"name": "X", "screens": None}}, rows("x"))["percent"] is None
