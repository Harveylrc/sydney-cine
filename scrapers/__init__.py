"""Base class for venue scrapers.

Each venue module subclasses BaseScraper, uses self.get() for every request and
implements fetch() -> list[Showing].
"""

import hashlib
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests

from models import Showing

USER_AGENT = "sydney-cine/0.1 (+contact in README)"
MIN_INTERVAL = 1.0  # seconds between requests to the same host
CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"


class BaseScraper:
    # Shared across all scrapers so two venues on one host (e.g. Veezi) still
    # respect the per-host limit.
    _last_request: dict[str, float] = {}

    def __init__(self, cache_dir: Path = CACHE_DIR):
        self.cache_dir = cache_dir
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT

    def get(self, url: str, **kwargs) -> requests.Response:
        """GET url, throttled per host, and save the raw body under cache/."""
        host = urlsplit(url).netloc
        self._wait_for(host)
        response = self.session.get(url, timeout=30, **kwargs)
        BaseScraper._last_request[host] = time.monotonic()
        response.raise_for_status()
        self._save(host, url, response.content)
        return response

    def fetch(self) -> list[Showing]:
        raise NotImplementedError

    def _wait_for(self, host: str) -> None:
        last = BaseScraper._last_request.get(host)
        if last is not None:
            remaining = MIN_INTERVAL - (time.monotonic() - last)
            if remaining > 0:
                time.sleep(remaining)

    def _save(self, host: str, url: str, body: bytes) -> None:
        name = hashlib.sha256(url.encode()).hexdigest()[:16]
        path = self.cache_dir / host / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
