PY := .venv/bin/python

.PHONY: venv lint test check

venv:
	python3.12 -m venv .venv
	$(PY) -m pip install -r requirements-dev.txt

lint:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

test:
	$(PY) -m pytest -q

check: lint test
