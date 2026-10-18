from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
import yaml

from scripts.paste_to_manual import ask_claude, entries_from, merge, save

SYDNEY = ZoneInfo("Australia/Sydney")
NOW = datetime(2026, 10, 19, 9, 0, tzinfo=SYDNEY)

REPLY = """Here are the screenings.

```yaml
- date: 2026-10-22
  time: "19:00"
  title: Vivre sa vie
  year: 1962
  director: Jean-Luc Godard
  tags: [35mm]
- date: 2026-10-25
  time: "2:30"
  title: Cléo from 5 to 7
```"""


class FakeClient:
    def __init__(self, reply):
        self.reply, self.sent = reply, None
        self.messages = self

    def create(self, **kwargs):
        self.sent = kwargs
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.reply)])


def test_prompt_carries_page_venue_and_date():
    client = FakeClient(REPLY)
    reply = ask_claude(client, "Sydney Cinémathèque", "PAGE TEXT", date(2026, 10, 19))
    prompt = client.sent["messages"][0]["content"]
    assert "PAGE TEXT" in prompt and "Sydney Cinémathèque" in prompt
    assert "2026-10-19 (Monday)" in prompt
    assert reply == REPLY


def test_entries_from_yaml_block():
    vivre, cleo = entries_from(REPLY)
    assert vivre["date"] == date(2026, 10, 22) and vivre["time"] == "19:00"
    assert vivre["director"] == "Jean-Luc Godard" and vivre["tags"] == ["35mm"]
    assert cleo["time"] == "02:30"


@pytest.mark.parametrize(
    "reply",
    ["```yaml\nnot: a list\n```", "```yaml\n- {date: 2026-10-22, title: No Time}\n```"],
)
def test_unusable_reply_rejected(reply):
    with pytest.raises(ValueError):
        entries_from(reply)


def test_merge_keeps_upcoming_without_doubles():
    existing = [
        {"date": "2026-10-18", "time": "19:00", "title": "Gone"},
        {"date": "2026-10-22", "time": "19:00", "title": "Vivre Sa Vie"},
    ]
    merged = merge(existing, entries_from(REPLY), NOW)
    assert [(e["date"].isoformat(), e["title"]) for e in merged] == [
        ("2026-10-22", "Vivre Sa Vie"),  # already there: kept once
        ("2026-10-25", "Cléo from 5 to 7"),
    ]


def test_save_writes_a_file_the_scraper_reads(tmp_path):
    from scrapers import manual

    path = tmp_path / "test-venue.yaml"
    venue = {"slug": "test-venue", "name": "Test Venue"}
    save(
        path, venue, merge([], entries_from(REPLY), NOW), "https://example.org", date(2026, 10, 19)
    )
    data = yaml.safe_load(path.read_text())
    assert data["updated"] == date(2026, 10, 19) and data["source"] == "https://example.org"
    titles = [s.film_title for s in manual.fetch(tmp_path, NOW)]
    assert titles == ["Vivre sa vie (1962)", "Cléo from 5 to 7"]
