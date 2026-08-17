# 0003 — Build the pipeline per session, not at import

**Status:** Accepted

## Context

The original code read `STT_PROVIDER`, `LLM_MODEL` and similar as module-level
constants evaluated at import. A process could therefore serve exactly one
configuration for its entire lifetime, and changing a config meant a restart.

## Decision

`build_stt/llm/tts/vad` each take a `StageConfig` and are called **inside**
`session()`, the LiveKit job entrypoint. No module-level provider globals anywhere.

## Consequences

- One worker serves every config. "Edit a config, press Run again" needs no restart.
- Measured cost: **~80 ms per call** (Gemini client ~40 ms, Silero model load ~40 ms;
  STT and TTS clients are free to construct), against ~1.93 s of process cold start.
- This is also the property multi-tenancy requires — one worker serving different
  customers' agents. The decision was made for convenience and turned out structural.
- If the cost ever matters, cache stage builds keyed by the stage config; identical
  stages are reusable (Silero VAD takes no options at all).
