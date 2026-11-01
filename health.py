"""Venue health (B32; DECISIONS 2026-11-01 v2.1.1 (1)).

After the export, each venue's session count is compared with the data.json that
was live before tonight's run. A venue that falls to 0, or below DROP of its
previous count, is a problem: usually a scraper broken by a markup change (Ritz,
2026-11-02: a sold-out session's link had no href and the whole venue went).

For one night, such a venue keeps the previous data.json's sessions that are
still ahead (from today on), flagged "stale": true, so the page doesn't go blank;
tonight's own sessions there are kept too, and a previous session is only added
where tonight has none at that venue, time and title. A venue whose previous
sessions were already stale is not kept again. Problems go to the GitHub job
summary and as a warning annotation on the run.
"""

import os
from collections import Counter

DROP = 0.25


def apply(data: dict, previous: dict | None, last_day: str) -> list[dict]:
    """Find problem venues and keep their previous sessions in data (showings and
    films; the caller recomputes what is derived from them), up to last_day, the
    horizon's last display day. Returns one dict per problem: venue, name, before,
    now, kept, second_night."""
    if not previous:
        return []
    old_rows = previous.get("showings", [])
    before = Counter(row["venue"] for row in old_rows)
    now = Counter(row["venue"] for row in data["showings"])
    names = {**previous.get("venues", {}), **data.get("venues", {})}
    have = {(row["venue"], row["start"], row["title"]) for row in data["showings"]}
    old_films = {film["id"]: film for film in previous.get("films", [])}
    films = {film["id"] for film in data["films"]}

    problems = []
    for venue, count in sorted(before.items()):
        tonight = now.get(venue, 0)
        if tonight and tonight >= DROP * count:
            continue
        mine = [row for row in old_rows if row["venue"] == venue]
        ahead = [row for row in mine if data["today"] <= row["day"] <= last_day]
        second_night = any(row.get("stale") for row in mine)
        kept = []
        if not second_night:
            kept = [
                {**row, "stale": True}
                for row in ahead
                if (row["venue"], row["start"], row["title"]) not in have
            ]
        data["showings"].extend(kept)
        for row in kept:
            if row["film"] not in films and row["film"] in old_films:
                data["films"].append(old_films[row["film"]])
                films.add(row["film"])
        problems.append(
            {
                "venue": venue,
                "name": names.get(venue, {}).get("name", venue),
                "before": count,
                "now": tonight,
                "kept": len(kept),
                "second_night": second_night,
            }
        )
    if problems:
        data["showings"].sort(key=lambda row: (row["start"], row["title"]))
        data["films"].sort(key=lambda film: film["title"].casefold())
    return problems


def report(problems: list[dict]) -> None:
    """Log each problem; on GitHub, a warning annotation each and a job summary."""
    lines = []
    for p in problems:
        if p["second_night"]:
            kept = "not kept: already kept last night"
        else:
            kept = f"kept {p['kept']} of last night's sessions"
        counts = f"{p['now']} sessions, {p['before']} last night"
        lines.append(f"{p['name']} ({p['venue']}): {counts}; {kept}")
    for line in lines:
        print(f"Venue health: {line}")
    if not os.environ.get("GITHUB_ACTIONS"):
        return
    for line in lines:
        print(f"::warning title=Venue health::{line}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as out:
            out.write("## Venue health\n\n")
            if not problems:
                out.write("Every venue is within range of last night.\n")
                return
            out.write("| Venue | Tonight | Last night | Kept from last night |\n")
            out.write("|---|---|---|---|\n")
            for p in problems:
                kept = "no (second night)" if p["second_night"] else str(p["kept"])
                out.write(f"| {p['name']} | {p['now']} | {p['before']} | {kept} |\n")
