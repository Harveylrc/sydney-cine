PY := .venv/bin/python

.PHONY: venv lint test check reading-refresh

venv:
	python3.12 -m venv .venv
	$(PY) -m pip install -r requirements-dev.txt

lint:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

test:
	$(PY) -m pytest -q

check: lint test

# Reading's API answers Australian addresses only (DECISIONS 2026-10-19). Run this
# over the AU VPN about once a week: it fetches all three cinemas, saves
# cache/reading-latest.json, and commits and pushes it for the nightly job.
reading-refresh:
	$(PY) -m scrapers.reading --refresh
	git add cache/reading-latest.json
	git commit -m "Reading: refresh saved sessions" cache/reading-latest.json
	git -c credential.helper= -c 'credential.helper=!gh auth git-credential' push
