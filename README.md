# sydney-cine

Sydney Cinema Guide: one filterable page of showtimes across Sydney's cinemas, chains and
independents alike, enriched with year, director and ratings from TMDB, so you can
search by film, director, type and date instead of visiting every cinema's site. The
scrapers identify themselves as `sydney-cine/0.1`, make at most one request per second
per site, respect robots.txt, and never touch ticket-purchase pages. If you run a
cinema and want your listings handled differently or removed, contact
harveylrc@proton.me.

## How it runs

Every night at 03:00 Sydney time a GitHub Actions job (`.github/workflows/nightly.yml`)
scrapes each cinema, matches the films on TMDB (asking Claude when the rules are
unsure), writes `public/data.json` (and `films.json`, the posters and synopses the film panel loads on first use) and publishes `public/` to GitHub Pages at
https://harveylrc.github.io/sydney-cine/. It reads the published `data.json` first so
"new this week" dates carry over, and keeps its TMDB lookup cache between runs.
"Run workflow" on the repository's Actions tab runs it immediately.

It needs two repository secrets, `TMDB_API_KEY` and `ANTHROPIC_API_KEY` (Settings →
Secrets and variables → Actions), and Settings → Pages → Source set to "GitHub
Actions". Locally, the same keys go in `.env` (see `.env.example`); `make check` runs
the linter and tests, and `python export.py` builds `public/data.json`.
