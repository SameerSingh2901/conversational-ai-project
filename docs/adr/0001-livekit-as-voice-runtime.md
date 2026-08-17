# 0001 — LiveKit Agents as the voice runtime

**Status:** Accepted

## Context

The product needs WebRTC transport, voice-activity detection, turn detection,
interruption handling and transcript streaming before it can hold a conversation.

## Options

1. Build the loop directly — WebRTC, VAD, turn-taking, barge-in.
2. Pipecat or a similar open-source orchestration framework.
3. A speech-to-speech model (OpenAI Realtime, Gemini Live).
4. **LiveKit Agents.**

## Decision

LiveKit Agents.

The deciding factor was not convenience. A speech-to-speech model **is** the
pipeline — there is no STT to swap and no TTS to configure — which would make the
entire config-driven premise impossible. The choice was really "modular pipeline or
single multimodal model", and everything else followed from picking the first.

## Consequences

- Gained: transport, trained turn detection, barge-in, transcript publishing,
  per-job process isolation — the parts that are hard to get subtly right.
- **Cost: a higher latency floor.** A cascaded STT → LLM → TTS pipeline is inherently
  slower than speech-to-speech. Swappability was bought with milliseconds.
- We inherit their execution model: plugins register on the main thread (see
  `pipeline.py`), and `ctx.room` is not connected in the entrypoint (see `agent.py`).
- We inherit their release cadence. Two CLI subcommands were deprecated mid-build.
- The abstraction hides per-stage latency, which is the number most worth seeing.
