"""Config CRUD.

Bodies are raw JSON handed to `parse_config()`. Invalid documents raise
`ConfigValidationError`, which the app's handler turns into a 422 carrying every
field error at once so the form can highlight all of them in one pass.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from voice_agent.config.env import missing_credentials
from voice_agent.config.schema import AgentConfig, parse_config
from voice_agent.config.store import ConfigNotFoundError, ConfigStore

router = APIRouter(tags=["configs"])


def _store(request: Request) -> ConfigStore:
    store: ConfigStore = request.app.state.store
    return store


def _summary(config: AgentConfig) -> dict[str, Any]:
    """Just enough for the sidebar list, without shipping the whole prompt."""
    return {
        "id": config.id,
        "name": config.name,
        "created_at": config.created_at,
        "stt": config.stt.provider,
        "llm": config.llm.provider,
        "tts": config.tts.provider,
        "missing_credentials": missing_credentials(config),
    }


@router.get("/configs")
async def list_configs(request: Request) -> list[dict[str, Any]]:
    return [_summary(c) for c in _store(request).list()]


@router.get("/configs/{config_id}")
async def get_config(config_id: str, request: Request) -> dict[str, Any]:
    try:
        config = _store(request).load(config_id)
    except ConfigNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        **config.to_dict(),
        "missing_credentials": missing_credentials(config),
    }


@router.post("/configs", status_code=201)
async def create_config(request: Request) -> dict[str, Any]:
    """Validate and save. Every save mints a new id, so history is preserved."""
    config = parse_config(await request.json())
    saved = _store(request).save(config)
    return {
        **saved.to_dict(),
        "missing_credentials": missing_credentials(saved),
    }


@router.post("/configs/validate")
async def validate_config(request: Request) -> dict[str, Any]:
    """Check without saving — lets the form report problems before the user commits."""
    config = parse_config(await request.json())
    return {"valid": True, "missing_credentials": missing_credentials(config)}
