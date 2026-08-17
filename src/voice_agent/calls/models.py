"""What we keep about a call.

This first increment is an overview: when it ran, which config produced it, what
it cost in tokens and characters, and how it ended. Per-turn latency and the
stored transcript come next — the shape here leaves room for both rather than
guessing at them now.

`call_id` is the LiveKit room name. That is unique per call and, crucially, the
browser already knows it from `POST /api/sessions`, so the UI can ask for a
record without a second identifier to thread through.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

RECORD_VERSION = 1

OUTCOME_COMPLETED = "completed"
OUTCOME_ERROR = "error"


@dataclass(frozen=True)
class TokenUsage:
    """What the LLM billed for. Cached prompt tokens are usually cheaper, so they
    are kept separately rather than folded into the prompt total."""

    prompt_tokens: int = 0
    prompt_cached_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "prompt_cached_tokens": self.prompt_cached_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(frozen=True)
class CallTotals:
    """The three things providers actually invoice: tokens, characters, audio."""

    tokens: TokenUsage = field(default_factory=TokenUsage)
    tts_characters: int = 0
    stt_audio_seconds: float = 0.0
    llm_requests: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "tokens": self.tokens.to_dict(),
            "tts_characters": self.tts_characters,
            "stt_audio_seconds": round(self.stt_audio_seconds, 2),
            "llm_requests": self.llm_requests,
        }


@dataclass(frozen=True)
class ToolUse:
    """How often each tool was called, and how often it reported failure."""

    name: str
    calls: int = 0
    errors: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "calls": self.calls, "errors": self.errors}


@dataclass(frozen=True)
class CallRecord:
    call_id: str
    config_id: str
    config_name: str
    config: dict[str, Any]
    """Full snapshot. The config file may be edited or deleted after the call;
    a record that pointed at it by id would silently start describing something
    else."""

    started_at: str
    ended_at: str | None = None
    duration_seconds: float | None = None
    outcome: str = OUTCOME_COMPLETED
    error: str | None = None
    shutdown_reason: str | None = None

    user_turns: int = 0
    agent_turns: int = 0
    tools: tuple[ToolUse, ...] = ()
    totals: CallTotals = field(default_factory=CallTotals)
    version: int = RECORD_VERSION

    @property
    def providers(self) -> dict[str, str]:
        """Denormalised from the snapshot so a listing need not parse the config."""
        return {
            stage: str(self.config.get(stage, {}).get("provider", ""))
            for stage in ("stt", "llm", "tts", "vad")
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "call_id": self.call_id,
            "config_id": self.config_id,
            "config_name": self.config_name,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_seconds": self.duration_seconds,
            "outcome": self.outcome,
            "error": self.error,
            "shutdown_reason": self.shutdown_reason,
            "user_turns": self.user_turns,
            "agent_turns": self.agent_turns,
            "providers": self.providers,
            "tools": [t.to_dict() for t in self.tools],
            "totals": self.totals.to_dict(),
            "config": self.config,
        }

    def summary(self) -> dict[str, Any]:
        """Enough for a list view, without shipping the whole config."""
        return {
            "call_id": self.call_id,
            "config_id": self.config_id,
            "config_name": self.config_name,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_seconds": self.duration_seconds,
            "outcome": self.outcome,
            "user_turns": self.user_turns,
            "agent_turns": self.agent_turns,
            "providers": self.providers,
            "total_tokens": self.totals.tokens.total_tokens,
            "tool_calls": sum(t.calls for t in self.tools),
        }


def record_from_dict(raw: dict[str, Any]) -> CallRecord:
    """Rebuild a record read back from disk.

    Deliberately forgiving about unknown keys: a record written by a newer version
    should still be listable rather than making the whole page fail.
    """
    totals_raw = raw.get("totals") or {}
    tokens_raw = totals_raw.get("tokens") or {}
    return CallRecord(
        call_id=str(raw.get("call_id", "")),
        config_id=str(raw.get("config_id", "")),
        config_name=str(raw.get("config_name", "")),
        config=dict(raw.get("config") or {}),
        started_at=str(raw.get("started_at", "")),
        ended_at=raw.get("ended_at"),
        duration_seconds=raw.get("duration_seconds"),
        outcome=str(raw.get("outcome", OUTCOME_COMPLETED)),
        error=raw.get("error"),
        shutdown_reason=raw.get("shutdown_reason"),
        user_turns=int(raw.get("user_turns", 0)),
        agent_turns=int(raw.get("agent_turns", 0)),
        tools=tuple(
            ToolUse(
                name=str(t.get("name", "")),
                calls=int(t.get("calls", 0)),
                errors=int(t.get("errors", 0)),
            )
            for t in raw.get("tools") or []
        ),
        totals=CallTotals(
            tokens=TokenUsage(
                prompt_tokens=int(tokens_raw.get("prompt_tokens", 0)),
                prompt_cached_tokens=int(tokens_raw.get("prompt_cached_tokens", 0)),
                completion_tokens=int(tokens_raw.get("completion_tokens", 0)),
                total_tokens=int(tokens_raw.get("total_tokens", 0)),
            ),
            tts_characters=int(totals_raw.get("tts_characters", 0)),
            stt_audio_seconds=float(totals_raw.get("stt_audio_seconds", 0.0)),
            llm_requests=int(totals_raw.get("llm_requests", 0)),
        ),
        version=int(raw.get("version", RECORD_VERSION)),
    )
