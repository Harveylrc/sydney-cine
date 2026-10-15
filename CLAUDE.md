# sydney-cine — working agreement for Claude Code

## What this is
A single filterable page of showtimes across every Sydney cinema (chains and
independents), searchable by film, director, type, date, release date and
retrospective — not by venue. See SPEC.md. If it is not in SPEC.md, do not build it.

## Stack (confirmed 2026-10-15)
- Python 3.12 for scrapers and enrichment; `requests` + `beautifulsoup4` for HTML,
  plain `requests` for JSON sources; SQLite as the store.
- Nightly GitHub Actions job runs the scrapers and TMDB enrichment, writes
  `public/data.json`, and deploys `public/` to GitHub Pages.
- Frontend: one `index.html` with vanilla JS that loads `data.json` and filters
  client-side. No framework, no build step.
- Enrichment via TMDB API (year, director, ratings). Keys in .env locally and in
  GitHub Actions secrets; never committed.

## Conventions
- One scraper per venue group under `scrapers/`, each exposing `fetch() -> list[Showing]`
  using the dataclass in `models.py`. Respect robots.txt; cache raw responses in `cache/`.
- Every scraper: User-Agent `sydney-cine/0.1 (+contact in README)`, ≤1 req/s per host,
  all times converted to Australia/Sydney before leaving the scraper.
- Tests in `tests/`, run with `pytest`. Every scraper ships with a fixture of the saved
  HTML or JSON it parses, so tests run offline.
- Branch per task from TASKS.md: `task/<id>-<slug>`. Small diffs; one task per PR.
- Run `make check` (lint + tests) before declaring a task done.

## How to work
1. Read SPEC.md, DECISIONS.md and TASKS.md. Pick the task you were told to do; do only that.
2. DECISIONS.md holds the per-venue access details (URLs, keys, gotchas). Use them;
   do not re-discover them.
3. If the task needs a decision the spec doesn't make, stop and write the question
   into DECISIONS.md under "Open" — do not improvise.
4. On finish: tick the task in TASKS.md, append one line to LOG.md (what you did,
   what you were unsure about).
5. The person you work with is new to programming. Explain what you did and why in
   plain language at the end of each task, and name the exact commands they should
   run next.

## Do not
- Add venues, features or integrations not in SPEC.md
- Fetch any URL that robots.txt disallows, or any purchase/ticketing page
- Store anything personal; no analytics beyond a page-view count
