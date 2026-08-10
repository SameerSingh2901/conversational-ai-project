"""FastAPI application: the control plane the UI talks to.

Deliberately does not use pydantic models for request bodies. FastAPI ships with
pydantic, but the validation this project needs already lives in
`voice_agent.config.schema`, and routing everything through `parse_config()` keeps
one validator rather than two that can disagree. Bodies are read as raw JSON and
handed straight to it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from voice_agent.api.routes import configs, providers, sessions
from voice_agent.config.errors import ConfigValidationError
from voice_agent.config.store import ConfigStore

# src/voice_agent/api/app.py -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_UI_DIR = REPO_ROOT / "ui"


def _load_dotenv() -> None:
    """Best-effort .env load so credential gating reflects the developer's keys."""
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - dotenv is a declared dependency
        return
    load_dotenv()


def create_app(
    config_dir: Path | str | None = None,
    ui_dir: Path | str | None = None,
) -> FastAPI:
    _load_dotenv()

    app = FastAPI(title="Voice Agent", version="0.1.0")
    app.state.store = ConfigStore(
        config_dir or os.environ.get("VOICE_AGENT_CONFIG_DIR", "configs")
    )

    @app.exception_handler(ConfigValidationError)
    async def _on_validation_error(
        _request: Request, exc: ConfigValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "errors": [{"loc": list(e.loc), "msg": e.msg} for e in exc.errors]
            },
        )

    @app.exception_handler(json.JSONDecodeError)
    async def _on_bad_json(
        _request: Request, exc: json.JSONDecodeError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={
                "errors": [
                    {"loc": [], "msg": f"invalid JSON: {exc.msg} at line {exc.lineno}"}
                ]
            },
        )

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "configs": str(app.state.store.root)}

    app.include_router(providers.router, prefix="/api")
    app.include_router(configs.router, prefix="/api")
    app.include_router(sessions.router, prefix="/api")

    # Mounted last so /api/* wins. html=True serves index.html at "/".
    ui_setting = ui_dir or os.environ.get("VOICE_AGENT_UI_DIR") or DEFAULT_UI_DIR
    resolved_ui = Path(ui_setting)
    if resolved_ui.is_dir():
        app.mount("/", StaticFiles(directory=resolved_ui, html=True), name="ui")

    return app


app = create_app()
