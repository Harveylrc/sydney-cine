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
unsure), writes `public/data.json` (and `films.json`, the posters and running times a film row loads when first opened) and publishes `public/` to GitHub Pages at
https://sydneycinema.com/ (the old https://harveylrc.github.io/sydney-cine/ address
redirects there). It reads the published `data.json` first so
"new this week" dates carry over, and keeps its TMDB lookup cache between runs.
On the 1st of each month it also rebuilds `directors.json`, the ~2,000 directors the
Director field suggests (`python -m scripts.build_directors`, about 10 minutes).
"Run workflow" on the repository's Actions tab runs it immediately.

It needs two repository secrets, `TMDB_API_KEY` and `ANTHROPIC_API_KEY` (Settings →
Secrets and variables → Actions), and Settings → Pages → Source set to "GitHub
Actions", with Custom domain `sydneycinema.com` and Enforce HTTPS ticked (`public/CNAME`
records the domain, but GitHub only reads it for sites it builds itself, so the
Settings entry is what counts). DNS for the domain (at Cloudflare): A records for
`sydneycinema.com` to 185.199.108.153, 185.199.109.153, 185.199.110.153 and
185.199.111.153, and a CNAME for `www` to `harveylrc.github.io`, all "DNS only".
Reading's API answers Australian addresses only, so the nightly job (in the US)
uses `cache/reading-latest.json`, a saved copy refreshed from an Australian
connection with `make reading-refresh` about once a week (it commits and pushes
the file); a copy over 8 days old is ignored and Reading shows nothing.
Locally, the same keys go in `.env` (see `.env.example`); `make check` runs
the linter and tests, and `python export.py` builds `public/data.json`.
