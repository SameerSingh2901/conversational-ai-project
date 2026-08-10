.DEFAULT_GOAL := check

.PHONY: init install lock-check fmt fmt-check lint type-check test test-cov check lock ui worker agent agent-text configs

# The two processes the UI needs. Run them in separate terminals:
#   make ui       -> http://localhost:8000, the config editor and Run button
#   make worker   -> connects to LiveKit Cloud, waits for rooms
#
# The worker takes NO config here on purpose: each call carries its own config as
# room metadata, so editing a config and hitting Run again needs no restart.
worker:
	lk agent dev src/voice_agent/agent.py

# Config editor + API on http://localhost:8000
# The UI is plain HTML/JS served by FastAPI, so this is the only process needed.
ui:
	uv run uvicorn voice_agent.api.app:app --reload --port 8000

# Talk to a saved config in the terminal. Requires the LiveKit CLI:
#   brew install livekit-cli
#
#   make agent CONFIG=sample-agent-20260809-132143        voice
#   make agent-text CONFIG=sample-agent-20260809-132143   typed, no mic
#
# `make configs` lists the ids. `lk agent console` replaces the agent's own
# `console` subcommand, which LiveKit has deprecated.
agent:
	VOICE_AGENT_CONFIG=$(CONFIG) lk agent console src/voice_agent/agent.py

# Text mode still runs the LLM and the prompt but skips the mic, STT and TTS —
# the quick way to iterate on a prompt without spending STT/TTS credits.
agent-text:
	VOICE_AGENT_CONFIG=$(CONFIG) lk agent console --text src/voice_agent/agent.py

configs:
	@ls -1 configs/*.json 2>/dev/null | xargs -n1 basename | sed 's/\.json$$//' || echo "(none saved yet)"

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
