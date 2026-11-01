import health

TODAY = "2026-11-02"
LAST_DAY = "2026-11-15"


def row(venue, day, hour, film="tmdb:1", title="Film", **extra):
    return {
        "film": film,
        "title": title,
        "venue": venue,
        "regions": ["East"],
        "start": f"{day}T{hour:02d}:00:00+11:00",
        "day": day,
        "time": f"{hour % 12 or 12}:00 pm",
        "late": False,
        "type": "new_release",
        "attributes": [],
        "booking_url": None,
        **extra,
    }


def film(fid, title):
    return {"id": fid, "title": title}


def ritz_night(n, day="2026-11-03"):
    return [row("ritz-randwick", day, 19) for _ in range(n)]


def make(showings, films=None):
    return {
        "today": TODAY,
        "venues": {
            "ritz-randwick": {"name": "Ritz Randwick"},
            "palace-norton": {"name": "Palace Norton St"},
        },
        "films": films or [film("tmdb:1", "Film")],
        "showings": showings,
        "days": {},
    }


def unique(rows):
    """Distinct start times, so rows don't collide on (venue, start, title)."""
    for i, r in enumerate(rows):
        r["start"] = f"{r['day']}T{10 + i // 60:02d}:{i % 60:02d}:00+11:00"
    return rows


def test_venue_falling_to_zero_keeps_last_nights_sessions():
    previous = make(unique(ritz_night(276)) + [row("palace-norton", "2026-11-03", 19)])
    data = make([row("palace-norton", "2026-11-03", 19)])
    problems = health.apply(data, previous, LAST_DAY)
    assert [(p["venue"], p["before"], p["now"], p["kept"]) for p in problems] == [
        ("ritz-randwick", 276, 0, 276)
    ]
    ritz = [r for r in data["showings"] if r["venue"] == "ritz-randwick"]
    assert len(ritz) == 276 and all(r["stale"] for r in ritz)
    assert not any(r.get("stale") for r in data["showings"] if r["venue"] == "palace-norton")


def test_healthy_venues_untouched():
    previous = make(unique(ritz_night(100)))
    data = make(unique(ritz_night(80)))
    assert health.apply(data, previous, LAST_DAY) == []
    assert len(data["showings"]) == 80


def test_drop_below_a_quarter_is_a_problem_and_only_adds_whats_missing():
    previous = make(unique(ritz_night(100)))
    data = make(unique(ritz_night(20)))  # the same first 20 sessions
    problems = health.apply(data, previous, LAST_DAY)
    assert [(p["now"], p["kept"]) for p in problems] == [(20, 80)]
    assert len(data["showings"]) == 100
    assert sum(bool(r.get("stale")) for r in data["showings"]) == 80


def test_past_and_beyond_horizon_sessions_not_kept():
    previous = make(
        [
            row("ritz-randwick", "2026-11-01", 19),
            row("ritz-randwick", "2026-11-02", 19),
            row("ritz-randwick", "2026-11-16", 19),
        ]
    )
    data = make([])
    health.apply(data, previous, LAST_DAY)
    assert [r["day"] for r in data["showings"]] == ["2026-11-02"]


def test_kept_only_one_night():
    previous = make([row("ritz-randwick", "2026-11-03", 19, stale=True)])
    data = make([])
    problems = health.apply(data, previous, LAST_DAY)
    assert [(p["kept"], p["second_night"]) for p in problems] == [(0, True)]
    assert data["showings"] == []


def test_kept_sessions_bring_their_films():
    previous = make(
        [row("ritz-randwick", "2026-11-03", 19, film="tmdb:9", title="Gone Film")],
        films=[film("tmdb:1", "Film"), film("tmdb:9", "Gone Film")],
    )
    data = make([])
    health.apply(data, previous, LAST_DAY)
    assert [f["id"] for f in data["films"]] == ["tmdb:1", "tmdb:9"]


def test_no_previous_data():
    data = make([])
    assert health.apply(data, None, LAST_DAY) == []


def test_report_warns_and_writes_summary_on_github(tmp_path, monkeypatch, capsys):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    previous = make(unique(ritz_night(276)))
    data = make([])
    health.report(health.apply(data, previous, LAST_DAY))
    out = capsys.readouterr().out
    warning = "::warning title=Venue health::Ritz Randwick (ritz-randwick): 0 sessions, 276 last"
    assert warning in out
    assert "| Ritz Randwick | 0 | 276 | 276 |" in summary.read_text()


def test_report_quiet_summary_when_healthy(tmp_path, monkeypatch, capsys):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    health.report([])
    assert "::warning" not in capsys.readouterr().out
    assert "Every venue is within range" in summary.read_text()
