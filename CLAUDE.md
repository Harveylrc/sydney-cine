# sydney-cine — working agreement for Claude Code

## What this is
A single filterable page of showtimes across every Sydney cinema (chains and
independents), searchable by film, director, type, date, release date and
retrospective — not by venue. See SPEC.md. If it is not in SPEC.md, do not build it.

## Stack (proposed — confirm in planning before first build)
- Python 3.12 for scrapers and enrichment; SQLite as the store
- Nightly job writes a static JSON bundle; a single-page frontend (plain HTML/JS or
  Next.js static export) renders it. Host on Vercel or GitHub Pages.
- Enrichment via TMDB API (year, director, ratings). Keep API keys in .env, never committed.

## Conventions
- One scraper per venue group under `scrapers/`, each exposing `fetch() -> list[Showing]`
  using the dataclass in `models.py`. Respect robots.txt; cache raw HTML in `cache/`.
- Tests in `tests/`, run with `pytest`. Every scraper ships with a fixture of saved HTML.
- Branch per task from TASKS.md: `task/<id>-<slug>`. Small diffs; one task per PR.
- Run `make check` (lint + tests) before declaring a task done.

## How to work
1. Read SPEC.md and TASKS.md. Pick the task you were told to do; do only that.
2. If the task needs a decision the spec doesn't make, stop and write the question
   into DECISIONS.md under "Open" — do not improvise.
3. On finish: tick the task in TASKS.md, append one line to LOG.md (what you did,
   what you were unsure about).

## Do not
- Add venues, features or integrations not in SPEC.md
- Store anything personal; no analytics beyond a page-view count
