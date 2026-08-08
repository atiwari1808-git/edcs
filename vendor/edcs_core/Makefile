.PHONY: install dev lint test run-listener run-worker
install:
	python3.11 -m venv .venv && .venv/bin/pip install -U pip && .venv/bin/pip install .
dev:
	python3.11 -m venv .venv && .venv/bin/pip install -U pip && .venv/bin/pip install -e ".[dev]"
lint:
	.venv/bin/ruff check edcs scripts tests
test:
	.venv/bin/pytest tests/unit -v
run-listener:
	.venv/bin/python -m edcs.email_listener.imap_listener
run-worker:
	.venv/bin/python -m edcs.orchestrator
