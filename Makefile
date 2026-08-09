.DEFAULT_GOAL := check

.PHONY: init install lock-check fmt fmt-check lint type-check test test-cov check lock

# One-time bootstrap when starting a new project from this workbench.
# Runs on macOS, Linux, and Windows: uv supplies the interpreter, and the
# script itself is pure standard library.
init:
	uv run --no-project python init.py

install:
	uv sync --locked

lock-check:
	uv lock --check

lock:
	uv lock

# Rewrites files: reformats, and applies every autofixable lint rule
# (import sorting among them). Not reachable from `check`.
fmt:
	uv run ruff format .
	uv run ruff check --fix .

fmt-check:
	uv run ruff format --check .

lint:
	uv run ruff check .

type-check:
	uv run mypy

# Reports coverage. Does not enforce a threshold.
test-cov:
	uv run pytest --cov

# Fast path. No coverage.
test:
	uv run pytest

# Read-only: every target here checks, none of them rewrite files.
check: lock-check fmt-check lint type-check 
