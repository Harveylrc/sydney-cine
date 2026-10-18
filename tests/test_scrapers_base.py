import logging
from datetime import date
from unittest.mock import MagicMock

import pytest
import requests

import scrapers
from scrapers import USER_AGENT, BaseScraper, heading_dates, is_non_film


class FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    c = FakeClock()
    monkeypatch.setattr(scrapers.time, "monotonic", c.monotonic)
    monkeypatch.setattr(scrapers.time, "sleep", c.sleep)
    monkeypatch.setattr(BaseScraper, "_last_request", {})
    return c


@pytest.fixture
def scraper(tmp_path, clock):
    s = BaseScraper(cache_dir=tmp_path)
    response = MagicMock(content=b"<html>hi</html>")
    s.session.get = MagicMock(return_value=response)
    return s


def test_user_agent_set(tmp_path):
    assert BaseScraper(cache_dir=tmp_path).session.headers["User-Agent"] == USER_AGENT


def test_second_request_to_same_host_waits(scraper, clock):
    scraper.get("https://a.example/1")
    clock.now += 0.25
    scraper.get("https://a.example/2")
    assert clock.slept == [pytest.approx(0.75)]


def test_different_hosts_do_not_wait(scraper, clock):
    scraper.get("https://a.example/1")
    scraper.get("https://b.example/1")
    assert clock.slept == []


def test_no_wait_after_interval_passed(scraper, clock):
    scraper.get("https://a.example/1")
    clock.now += 1.5
    scraper.get("https://a.example/2")
    assert clock.slept == []


def test_raw_response_cached(scraper, tmp_path):
    scraper.get("https://a.example/page")
    files = list((tmp_path / "a.example").iterdir())
    assert len(files) == 1
    assert files[0].read_bytes() == b"<html>hi</html>"


def test_connection_failure_retried_once(scraper, clock, caplog):
    response = MagicMock(content=b"ok")
    scraper.session.get = MagicMock(
        side_effect=[requests.ConnectionError("name resolution"), response]
    )
    assert scraper.get("https://a.example/x") is response
    assert scraper.session.get.call_count == 2
    assert scrapers.RETRY_AFTER in clock.slept
    assert "trying again" in caplog.text


def test_second_connection_failure_raises(scraper):
    scraper.session.get = MagicMock(side_effect=requests.Timeout("slow"))
    with pytest.raises(requests.Timeout):
        scraper.get("https://a.example/x")
    assert scraper.session.get.call_count == 2


def test_http_error_not_retried(scraper):
    response = MagicMock()
    response.raise_for_status.side_effect = requests.HTTPError("404")
    scraper.session.get = MagicMock(return_value=response)
    with pytest.raises(requests.HTTPError):
        scraper.get("https://a.example/x")
    assert scraper.session.get.call_count == 1


def test_fetch_must_be_implemented(scraper):
    with pytest.raises(NotImplementedError):
        scraper.fetch()


@pytest.mark.parametrize(
    "title",
    [
        "Film Trivia",
        "Halloween Quiz Night",
        "The Orpheum Jazz Lounge - The Pocket Trio",
        "Comedy Store Presents Hayden Orpheum Comedy Club",
        "Saturday DJ Set",
        "Silent Disco Dance Party",
    ],
)
def test_non_film_events(title):
    assert is_non_film(title)


@pytest.mark.parametrize(
    "title",
    [
        "The Party",  # Blake Edwards, 1968
        "GFF26 The Birthday Party",
        "HYBE CHEERING PARTY",  # a fan screening TMDB lists as a film
        "Quiz Show",
        "Rammstein - Live in Mexico City",
        "BTS WORLD TOUR 'ARIRANG' IN SAO PAULO LIVE VIEWING",
        "Highlander - Christopher Lambert Live Q&A",
        "NT Live: Golden Boy",
        "Met Opera - Macbeth",
    ],
)
def test_screenings_kept(title):
    assert not is_non_film(title)


# --- year inference ---------------------------------------------------------------


def test_month_rollover_into_next_year():
    headings = ["Wednesday 30th December", "Thursday 31st December", "Friday 1st January"]
    assert heading_dates(headings, date(2026, 12, 30)) == [
        date(2026, 12, 30),
        date(2026, 12, 31),
        date(2027, 1, 1),
    ]


def test_first_heading_long_past_means_next_year():
    assert heading_dates(["Saturday 2nd January"], date(2026, 12, 30)) == [date(2027, 1, 2)]


def test_first_heading_a_little_past_stays_this_year():
    # A page cached a day behind: still this year.
    assert heading_dates(["Saturday 17th October"], date(2026, 10, 18)) == [date(2026, 10, 17)]


def test_wrong_weekday_logged(caplog):
    with caplog.at_level(logging.WARNING, logger="scrapers"):
        assert heading_dates(["Monday 18th October"], date(2026, 10, 18)) == [date(2026, 10, 18)]
    assert "is not a Monday in 2026" in caplog.text


@pytest.mark.parametrize("bad", ["Sunday 29th February", "Coming soon"])
def test_unusable_heading_skipped(bad, caplog):
    with caplog.at_level(logging.WARNING, logger="scrapers"):
        assert heading_dates([bad], date(2026, 10, 18)) == [None]


def test_veezi_style_heading():
    assert heading_dates(["Tuesday 20, October", "Sunday 24, January"], date(2026, 10, 18)) == [
        date(2026, 10, 20),
        date(2027, 1, 24),
    ]
