"""Starting a call from the browser.

The whole point of this route: the config travels to the worker as **room
metadata**. The API creates a room carrying the config, mints a token for the
browser, and the worker reads that metadata when it picks up the job. Nothing is
pinned at worker startup, so changing config and starting a new call needs no
restart — which is the property the Run button depends on.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from livekit import api

from voice_agent.config.env import (
    MissingCredentialsError,
    livekit_credentials,
    missing_credentials,
)
from voice_agent.config.schema import AgentConfig
from voice_agent.config.store import ConfigNotFoundError, ConfigStore

router = APIRouter(tags=["sessions"])

# Long enough to click Run, grant mic permission and start talking.
EMPTY_ROOM_TIMEOUT_S = 300
PARTICIPANT_IDENTITY = "browser-user"


def _store(request: Request) -> ConfigStore:
    store: ConfigStore = request.app.state.store
    return store


def _room_name(config: AgentConfig) -> str:
    """Unique per call, but readable enough to find in the LiveKit dashboard."""
    return f"{config.id}--{uuid.uuid4().hex[:8]}"


@router.post("/sessions", status_code=201)
async def create_session(request: Request) -> dict[str, Any]:
    body = await request.json()
    if not isinstance(body, dict) or not body.get("config_id"):
        raise HTTPException(status_code=422, detail="config_id is required")

    config_id = str(body["config_id"])
    try:
        config = _store(request).load(config_id)
    except ConfigNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    absent = missing_credentials(config)
    if absent:
        raise HTTPException(
            status_code=400,
            detail=f"this config needs credentials that are not set: {', '.join(absent)}",
        )

    try:
        creds = livekit_credentials()
    except MissingCredentialsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    room_name = _room_name(config)

    lkapi = api.LiveKitAPI(
        url=creds.http_url, api_key=creds.api_key, api_secret=creds.api_secret
    )
    try:
        await lkapi.room.create_room(
            api.CreateRoomRequest(
                name=room_name,
                empty_timeout=EMPTY_ROOM_TIMEOUT_S,
                metadata=json.dumps(config.to_dict()),
            )
        )
    finally:
        await lkapi.aclose()

    token = (
        api.AccessToken(creds.api_key, creds.api_secret)
        .with_identity(PARTICIPANT_IDENTITY)
        .with_name("You")
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room_name,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=True,
            )
        )
        .to_jwt()
    )

    return {
        "url": creds.url,
        "token": token,
        "room": room_name,
        "identity": PARTICIPANT_IDENTITY,
        "config_id": config.id,
        "config_name": config.name,
    }
