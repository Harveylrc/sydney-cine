# TASKS

## Planning (Fable) — done
- [x] P1 Confirm data access per venue; fill DECISIONS.md (2026-10-15)
- [x] P4 Browser capture pass: Palace, Orpheum solved; Reading inconclusive; Dendy out (2026-10-15)
- [x] P2 Stack confirmed in CLAUDE.md; SPEC.md v1 (2026-10-15)
- [x] P3 Build tasks written below (2026-10-15)

## Build (Opus, Claude Code) — one task per session, in order
Each task: branch `task/<id>-<slug>`, `make check` green, tick here, one line in LOG.md.

- [x] **B1 Repo skeleton** (done 2026-10-15 against the v0 brief — minimal `Showing`, ruff + pytest, Makefile).
- [x] **B1b Bring B1 up to the v1 brief.** Extend `models.Showing` to: venue_slug, venue_name, film_title, start (tz-aware Australia/Sydney), session_id, booking_url, attributes: list[str] (default empty), vista_movie_id: str | None, tmdb_id: int | None, year: int | None, director: str | None, rating: float | None. Update the existing tests. Add `scrapers/__init__.py` with a `BaseScraper` class: sets User-Agent `sydney-cine/0.1 (+contact in README)`, throttles to 1 request/second per host, caches raw responses under `cache/` (gitignored). Add `requirements.txt` (requests, beautifulsoup4). Replace README "Lorem ipsum" with one paragraph on what this is and a contact email. Acceptance: `make check` passes.
- [ ] **B2 Ritz scraper.** `scrapers/ritz.py` fetching `/now-showing/YYYY-MM-DD` for the next 14 days. Save one real day as `tests/fixtures/ritz_2026-10-16.html`; test parses it to the expected Showings (title, time, session id from `?s=`, tags). Acceptance: fixture test passes; a live run prints ≥1 showing.
- [ ] **B3 TMDB enrichment.** `enrich.py`: match by vista_movie_id across venues first, then TMDB search by title (+year if present); cache lookups in SQLite so a title is queried once. Fill tmdb_id, year, director, rating. Acceptance: test with a mocked TMDB response; unmatched titles are logged, not dropped.
- [ ] **B4 Export + page.** `export.py` writes `public/data.json` (showings + films). `public/index.html` loads it and filters by film, director, type, date, release date; grouped views "new this week", "retrospectives", "last chance". No framework. Acceptance: opening index.html locally over a static server shows Ritz showings with filters working.
- [ ] **B5a Hoyts** (JSON API, all NSW cinemas; fixture = saved `sessions/SHOWGR` JSON)
- [ ] **B5b Palace** (parse `__NEXT_DATA__` from `/cinemas/{slug}` for 3 Sydney slugs; convert UTC; fixture = saved HTML)
- [ ] **B5c Orpheum** (`/api/movie/playing-now`; fixture = saved JSON)
- [ ] **B5d Golden Age** (HTML, day headings; infer year from month rollover)
- [ ] **B5e Roseville** (Veezi sessions page; never fetch `/purchase`)
- [ ] **B5f Event** (printable week view for each Sydney slug; verify output matches a normal browser UA)
- [ ] **B6 Nightly job + deploy.** GitHub Actions: cron 03:00 Sydney, run scrapers → enrich → export → deploy `public/` to GitHub Pages. Secrets for TMDB. Acceptance: one scheduled run succeeds and the page is live.
- [ ] **B7 Coverage metric.** `coverage.py` computes % of Sydney screens covered (screen counts per venue in `venues.yaml`), written into data.json and shown on the page footer. Dendy and any failing venue count as uncovered.
- [ ] **B8 Reading retest** from an AU IP (after B6; GitHub Actions runners are US — may need a one-off run from Harvey's machine in Sydney). If still blank, record in DECISIONS.md as uncovered.
