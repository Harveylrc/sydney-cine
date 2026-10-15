# LOG — what the AI did well, where I intervened

2026-10-14 Scaffold written with Fable. Nothing built yet.
2026-10-15 P1 audit (Fable, 3 research subagents). Found Hoyts open JSON API, Ritz/Golden Age/Event server-rendered, Roseville via Veezi. Palace/Reading/Orpheum/Dendy JS-only — flagged for a browser pass. Found three venues in SPEC.md closed/renamed.
2026-10-15 Harvey: do the browser pass first; collapse Dendy to one entity.
2026-10-15 P4 browser pass (Fable via Claude in Chrome, ~15 min). Palace: full schedule sits in `__NEXT_DATA__`, no XHR. Orpheum: open `/api/movie/playing-now`. Reading: blank page from a Paris IP, nothing to capture. Dendy: confirmed `/graphql` only, left alone.
2026-10-15 P2/P3 (Fable). Stack confirmed: Python + SQLite + GitHub Actions + GitHub Pages + vanilla HTML/JS. SPEC v1 and B1–B8 written.
2026-10-15 B1 (Opus): repo skeleton — models.Showing (venue, title, starts_at, booking_url), Makefile (`make venv`, `make check` = ruff + pytest), pyproject, requirements-dev, .env.example; py3.12 venv. Unsure: planning P1–P3 still open (stack not formally confirmed); chose ruff as linter and kept Showing minimal — enrichment fields deferred to B3.
2026-10-15 Fable review of B1: clean and correct, but built against the v0 planning files (repo had this morning's copies). Opus flagged this itself — good. Updated planning files copied into the repo; added B1b to top B1 up to the v1 brief.
