"""What the UI is allowed to offer.

The catalogue comes from `providers.py`; this route only annotates each entry with
whether its credential is actually present. A provider that is supported but has no
key shows in the dropdown, disabled, with the env var it needs — which is more
useful than hiding it and leaving the user wondering where it went.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from voice_agent.config.env import available_providers
from voice_agent.config.providers import describe_stages

router = APIRouter(tags=["providers"])


@router.get("/providers")
async def get_providers() -> dict[str, Any]:
    described = describe_stages()
    available = available_providers()
    for stage, provider_list in described.items():
        usable = set(available[stage])
        for provider in provider_list:
            provider["available"] = provider["name"] in usable
    return described
