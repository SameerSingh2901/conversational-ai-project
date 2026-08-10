"""Credentials — read from the environment, never from a config file.

A provider is *supported* when a branch exists for it in `providers.py`, and
*available* when its credential is present here. The UI offers only what is both,
so enabling a provider you have already coded is a `.env` edit, not a code change.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from voice_agent.config.providers import STAGES, ProviderSpec
from voice_agent.config.schema import AgentConfig

LIVEKIT_VARS = ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")


class MissingCredentialsError(RuntimeError):
    """Required environment variables are absent."""

    def __init__(self, missing: list[str]) -> None:
        self.missing = missing
        super().__init__(f"missing environment variables: {', '.join(missing)}")


@dataclass(frozen=True)
class LiveKitCredentials:
    url: str
    api_key: str
    api_secret: str

    @property
    def http_url(self) -> str:
        """The server API speaks http(s); the browser joins over ws(s)."""
        if self.url.startswith("wss://"):
            return "https://" + self.url[len("wss://") :]
        if self.url.startswith("ws://"):
            return "http://" + self.url[len("ws://") :]
        return self.url


def livekit_credentials() -> LiveKitCredentials:
    values = {var: os.environ.get(var, "").strip() for var in LIVEKIT_VARS}
    missing = [var for var, value in values.items() if not value]
    if missing:
        raise MissingCredentialsError(missing)
    return LiveKitCredentials(
        url=values["LIVEKIT_URL"],
        api_key=values["LIVEKIT_API_KEY"],
        api_secret=values["LIVEKIT_API_SECRET"],
    )


def has_credential(spec: ProviderSpec) -> bool:
    if spec.credential is None:
        return True
    return bool(os.environ.get(spec.credential, "").strip())


def available_providers() -> dict[str, list[str]]:
    """Stage -> provider names that are usable with the credentials present."""
    return {
        stage: [name for name, spec in catalogue.items() if has_credential(spec)]
        for stage, catalogue in STAGES.items()
    }


def missing_credentials(config: AgentConfig) -> list[str]:
    """Env vars this config needs but that are not set. Empty means ready to run."""
    missing: list[str] = []
    selected = {
        "stt": config.stt.provider,
        "llm": config.llm.provider,
        "tts": config.tts.provider,
        "vad": config.vad.provider,
    }
    for stage, provider in selected.items():
        spec = STAGES[stage].get(provider)
        if spec is None or spec.credential is None:
            continue
        if not has_credential(spec) and spec.credential not in missing:
            missing.append(spec.credential)
    return missing
