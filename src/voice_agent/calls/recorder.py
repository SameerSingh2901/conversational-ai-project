"""Turning LiveKit's session events into one call record.

The recorder holds everything in memory for the duration of the call and writes
once, on shutdown. Nothing here touches disk while audio is flowing — the same
rule that keeps the Pinecone lookup off the event loop.

LiveKit emits metrics per stage, not per call, so this class is mostly counting.
The per-turn correlation (grouping metrics by `speech_id` into a latency
breakdown) is the next increment; this one answers "when, with what, how much".
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from voice_agent.calls.models import (
    OUTCOME_COMPLETED,
    OUTCOME_ERROR,
    CallRecord,
    CallTotals,
    TokenUsage,
    ToolUse,
)
from voice_agent.config.schema import AgentConfig

logger = logging.getLogger("voice-agent.calls")


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


class CallRecorder:
    """Accumulates one call's overview. Attach it to a session, finish it on shutdown.

    Every handler is defensive. A malformed metric must never take down a live
    call — losing a number is an acceptable price, losing the conversation is not.
    """

    def __init__(self, call_id: str, config: AgentConfig) -> None:
        self.call_id = call_id
        self._config = config
        self._started = _now()
        self._ended: datetime | None = None

        self._prompt_tokens = 0
        self._prompt_cached_tokens = 0
        self._completion_tokens = 0
        self._total_tokens = 0
        self._llm_requests = 0
        self._tts_characters = 0
        self._stt_audio_seconds = 0.0

        self._user_turns = 0
        self._agent_turns = 0
        self._tool_calls: dict[str, int] = {}
        self._tool_errors: dict[str, int] = {}

        self._error: str | None = None

    # --- wiring -----------------------------------------------------------

    def attach(self, session: Any) -> None:
        """Subscribe to the events this record is built from."""
        session.on("metrics_collected", self._on_metrics)
        session.on("conversation_item_added", self._on_item)
        session.on("function_tools_executed", self._on_tools)
        session.on("error", self._on_error)

    # --- handlers ---------------------------------------------------------

    def _on_metrics(self, event: Any) -> None:
        try:
            m = event.metrics
            kind = getattr(m, "type", "")
            if kind == "llm_metrics":
                self._llm_requests += 1
                self._prompt_tokens += int(getattr(m, "prompt_tokens", 0) or 0)
                self._prompt_cached_tokens += int(
                    getattr(m, "prompt_cached_tokens", 0) or 0
                )
                self._completion_tokens += int(getattr(m, "completion_tokens", 0) or 0)
                self._total_tokens += int(getattr(m, "total_tokens", 0) or 0)
            elif kind == "tts_metrics":
                self._tts_characters += int(getattr(m, "characters_count", 0) or 0)
            elif kind == "stt_metrics":
                self._stt_audio_seconds += float(
                    getattr(m, "audio_duration", 0.0) or 0.0
                )
        except Exception:  # a bad metric must not end a call
            logger.debug("could not record a metric", exc_info=True)

    def _on_item(self, event: Any) -> None:
        try:
            role = getattr(event.item, "role", "")
            if role == "user":
                self._user_turns += 1
            elif role == "assistant":
                self._agent_turns += 1
        except Exception:
            logger.debug("could not record a conversation item", exc_info=True)

    def _on_tools(self, event: Any) -> None:
        try:
            for call in getattr(event, "function_calls", []) or []:
                name = str(getattr(call, "name", "") or "unknown")
                self._tool_calls[name] = self._tool_calls.get(name, 0) + 1
            for output in getattr(event, "function_call_outputs", []) or []:
                if getattr(output, "is_error", False):
                    name = str(getattr(output, "name", "") or "unknown")
                    self._tool_errors[name] = self._tool_errors.get(name, 0) + 1
        except Exception:
            logger.debug("could not record a tool call", exc_info=True)

    def _on_error(self, event: Any) -> None:
        try:
            self._error = str(getattr(event, "error", "") or "unknown error")
        except Exception:
            logger.debug("could not record an error", exc_info=True)

    # --- result -----------------------------------------------------------

    def finish(self, shutdown_reason: str | None = None) -> CallRecord:
        self._ended = self._ended or _now()
        duration = (self._ended - self._started).total_seconds()

        tools = tuple(
            ToolUse(
                name=name,
                calls=count,
                errors=self._tool_errors.get(name, 0),
            )
            for name, count in sorted(self._tool_calls.items())
        )

        return CallRecord(
            call_id=self.call_id,
            config_id=self._config.id or self._config.name,
            config_name=self._config.name,
            config=self._config.to_dict(),
            started_at=_iso(self._started),
            ended_at=_iso(self._ended),
            duration_seconds=round(duration, 2),
            outcome=OUTCOME_ERROR if self._error else OUTCOME_COMPLETED,
            error=self._error,
            shutdown_reason=shutdown_reason,
            user_turns=self._user_turns,
            agent_turns=self._agent_turns,
            tools=tools,
            totals=CallTotals(
                tokens=TokenUsage(
                    prompt_tokens=self._prompt_tokens,
                    prompt_cached_tokens=self._prompt_cached_tokens,
                    completion_tokens=self._completion_tokens,
                    total_tokens=self._total_tokens,
                ),
                tts_characters=self._tts_characters,
                stt_audio_seconds=self._stt_audio_seconds,
                llm_requests=self._llm_requests,
            ),
        )
