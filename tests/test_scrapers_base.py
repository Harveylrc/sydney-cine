from unittest.mock import MagicMock

import pytest

import scrapers
from scrapers import USER_AGENT, BaseScraper, is_non_film


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
