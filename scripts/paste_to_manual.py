"""Turn a venue's programme, copied from your own browser, into manual/<venue>.yaml.

    pbpaste | .venv/bin/python -m scripts.paste_to_manual sydney-cinematheque

Reads the pasted page text from stdin, asks Claude (ANTHROPIC_API_KEY, as for
matching) to list its screenings as session entries, prints them, and saves them
only when you answer "y". Saving keeps the file's upcoming sessions, adds the new
ones (a session already there, same date, time and title, isn't doubled), drops
past ones and sets "updated". Check the dates and times before you say yes.
"""

import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import anthropic
import yaml

from enrich import CLAUDE_MODEL, load_env, normalise
from export import load_venues
from scrapers.manual import MANUAL_DIR, SYDNEY, clock

MAX_TOKENS = 16000

PROMPT = """Below is text copied from the programme page of {name}, a cinema in Sydney.
Today is {today} ({weekday}). List every screening on or after today as YAML: a list
of mappings with these keys, and nothing else in your reply but the YAML in one
```yaml block:

- date: YYYY-MM-DD   (when the text gives no year, pick the year that matches the
                      weekday it gives, or else the nearest one to today)
  time: "HH:MM"      (24-hour, Sydney time, quoted)
  title: the film's title only, without the director, year, format or event name
  year: the film's release year, if the text gives it (omit otherwise)
  director: the director, if the text gives it (omit otherwise)
  type: retrospective, new_release, festival or special, if the text makes it clear
        (omit otherwise)
  tags: a list of short notes the text gives about the screening, such as 35mm,
        Q&A, Introduced, Free (omit if none)
  url: a booking or information link for that screening, if the text includes one
       (omit otherwise)

One entry per screening: a film shown twice is two entries. Leave out screenings
before today, talks, exhibitions and anything that is not a film screening. Do not
guess times.

The page text:
<<<
{text}
>>>"""

YAML_BLOCK = re.compile(r"```(?:yaml)?\s*\n(.*?)```", re.DOTALL)
REQUIRED = ("date", "time", "title")
MAX_AHEAD = timedelta(days=180)  # further ahead than this is more likely a wrong year


def ask_claude(client, name: str, text: str, today: date) -> str:
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=MAX_TOKENS,
        messages=[
            {
                "role": "user",
                "content": PROMPT.format(
                    name=name, today=today.isoformat(), weekday=f"{today:%A}", text=text
                ),
            }
        ],
    )
    return "\n".join(b.text for b in response.content if b.type == "text")


def entries_from(reply: str) -> list[dict]:
    """The session entries in Claude's reply, checked; ValueError if unusable."""
    blocks = YAML_BLOCK.findall(reply)
    entries = yaml.safe_load(blocks[-1] if blocks else reply) or []
    if not isinstance(entries, list):
        raise ValueError("Claude's reply is not a list of sessions")
    for entry in entries:
        missing = [key for key in REQUIRED if not entry.get(key)]
        if missing:
            raise ValueError(f"Session without {', '.join(missing)}: {entry}")
        entry["date"] = date.fromisoformat(str(entry["date"]))
        entry["time"] = clock(entry["time"]).strftime("%H:%M")
    return entries


def start(entry: dict) -> datetime:
    return datetime.combine(entry["date"], clock(entry["time"]), tzinfo=SYDNEY)


def merge(existing: list[dict], new: list[dict], now: datetime) -> list[dict]:
    """Upcoming sessions from both, without doubles, in start order."""
    merged = {}
    for entry in existing + new:
        entry = dict(
            entry,
            date=date.fromisoformat(str(entry["date"])),
            time=clock(entry["time"]).strftime("%H:%M"),
        )
        if start(entry) >= now:
            merged.setdefault((entry["date"], entry["time"], normalise(entry["title"])), entry)
    return sorted(merged.values(), key=start)


def save(path: Path, venue: dict, sessions: list[dict], source: str | None, today: date) -> None:
    old = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    data = {
        "venue": venue["slug"],
        "name": venue["name"],
        "source": source or old.get("source"),
        "updated": today,
        **({"type": old["type"]} if old.get("type") else {}),
        "sessions": sessions,
    }
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def confirm(question: str) -> bool:
    """Ask on the terminal (stdin holds the pasted page)."""
    try:
        with open("/dev/tty") as tty:
            print(question, end=" ", flush=True)
            return tty.readline().strip().lower() in ("y", "yes")
    except OSError:
        return False


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    venues = load_venues()
    venue = venues.get(argv[0])
    if not venue:
        print(f"{argv[0]} is not in venues.yaml")
        return 2
    key = load_env("ANTHROPIC_API_KEY")
    if not key:
        print("ANTHROPIC_API_KEY is not set (.env)")
        return 2
    text = sys.stdin.read()
    if not text.strip():
        print("Nothing pasted: copy the programme page first (pbpaste | …)")
        return 2
    now = datetime.now(SYDNEY)
    entries = entries_from(
        ask_claude(anthropic.Anthropic(api_key=key), venue["name"], text, now.date())
    )
    upcoming = [e for e in entries if now <= start(e) <= now + MAX_AHEAD]
    for e in entries:
        if start(e) > now + MAX_AHEAD:
            print(f"Left out, over six months ahead (wrong year?): {e['date']} {e['title']}")
    print(yaml.safe_dump(upcoming, allow_unicode=True, sort_keys=False))
    print(
        f"{len(upcoming)} upcoming sessions found"
        f" ({len(entries) - len(upcoming)} past ones left out)."
    )
    path = MANUAL_DIR / f"{venue['slug']}.yaml"
    if not upcoming or not confirm(f"Save them to {path.relative_to(MANUAL_DIR.parent)}? [y/N]"):
        print("Not saved.")
        return 1
    old = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    sessions = merge(old.get("sessions") or [], upcoming, now)
    save(path, venue, sessions, venue.get("source_url"), now.date())
    print(f"Saved {len(sessions)} upcoming sessions. Commit and push the file to publish them.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
