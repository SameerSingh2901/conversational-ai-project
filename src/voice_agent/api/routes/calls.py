"""Reading call records.

The worker writes these; the API only reads. There is deliberately no endpoint
that creates or edits one — a call log the application can rewrite is not worth
much as a record of what happened.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from voice_agent.calls.store import CallNotFoundError, CallStore

router = APIRouter(tags=["calls"])


def _store(request: Request) -> CallStore:
    store: CallStore = request.app.state.calls
    return store


@router.get("/calls")
async def list_calls(request: Request) -> list[dict[str, Any]]:
    return [record.summary() for record in _store(request).list()]


@router.get("/calls/{call_id}")
async def get_call(call_id: str, request: Request) -> dict[str, Any]:
    """The full record. 404 while a call is still being written, which is what
    lets the browser poll after hang-up until the log appears."""
    try:
        record = _store(request).load(call_id)
    except CallNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return record.to_dict()
