"""The provider catalogue — the single source of truth for what can be configured.

Everything downstream reads this table:

* validation      — which fields a provider requires, and of what type
* the UI          — dropdown options and the fields to render for each choice
* credentials     — which env var must be set for a provider to be selectable
* the pipeline    — builders are registered against these same provider names

Adding a provider is one entry here plus one builder function. No other file needs
to change, and the UI picks it up automatically.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

# Stock ElevenLabs voice ("Rachel") — every account has it, so it is a safe default
# for a config that does not name one.
DEFAULT_ELEVENLABS_VOICE = "21m00Tcm4TlvDq8ikWAM"

# Verified working against a current Google AI Studio key (2026-08-09) by calling
# generateContent on each. `gemini-2.5-flash-lite` is deliberately absent: Google
# now returns 404 "no longer available to new users" for it, even though the models
# list endpoint still advertises it.
GEMINI_MODELS = (
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3.6-flash",
)
DEFAULT_GEMINI_MODEL = GEMINI_MODELS[0]

# A curated subset of Deepgram's Aura-2 voices, not the full catalogue. Extend the
# tuple to offer more; the UI follows.
DEEPGRAM_VOICES = (
    "aura-2-thalia-en",
    "aura-2-andromeda-en",
    "aura-2-apollo-en",
    "aura-2-arcas-en",
    "aura-2-asteria-en",
    "aura-2-athena-en",
    "aura-2-helena-en",
    "aura-2-hera-en",
    "aura-2-orion-en",
    "aura-2-zeus-en",
)

# Not Deepgram's full list — a working subset. Add to this tuple as needed; the UI
# picks it up with no other change. Note that support varies by model, so an odd
# pairing surfaces as a Deepgram API error rather than a validation error here.
DEEPGRAM_LANGUAGES = (
    "en",
    "en-US",
    "en-GB",
    "en-IN",
    "hi",
    "es",
    "fr",
    "de",
    "multi",
)


@dataclass(frozen=True)
class FieldSpec:
    """One configurable field belonging to one provider."""

    type: type
    required: bool = False
    default: Any = None
    choices: tuple[str, ...] | None = None
    description: str = ""


@dataclass(frozen=True)
class ProviderSpec:
    """One selectable provider for one pipeline stage."""

    name: str
    label: str
    fields: Mapping[str, FieldSpec] = field(default_factory=dict)
    credential: str | None = None
    """Env var required for this provider to be usable. None means no key needed."""


STT_PROVIDERS: dict[str, ProviderSpec] = {
    "deepgram": ProviderSpec(
        name="deepgram",
        label="Deepgram",
        credential="DEEPGRAM_API_KEY",
        fields={
            "model": FieldSpec(
                type=str,
                required=True,
                choices=("nova-3", "nova-2"),
                description="Deepgram speech-to-text model.",
            ),
            "language": FieldSpec(
                type=str,
                default="en",
                choices=DEEPGRAM_LANGUAGES,
                description="Spoken language. 'multi' detects and mixes languages.",
            ),
        },
    ),
}

LLM_PROVIDERS: dict[str, ProviderSpec] = {
    "google": ProviderSpec(
        name="google",
        label="Google Gemini",
        credential="GOOGLE_API_KEY",
        fields={
            "model": FieldSpec(
                type=str,
                default=DEFAULT_GEMINI_MODEL,
                choices=GEMINI_MODELS,
                description="Flash-Lite tiers are the low-latency ones — pick those "
                "for voice unless you need the reasoning.",
            ),
            "temperature": FieldSpec(
                type=float,
                default=0.7,
                description="Sampling temperature.",
            ),
        },
    ),
    "ollama": ProviderSpec(
        name="ollama",
        label="Ollama (local)",
        credential=None,
        fields={
            "model": FieldSpec(
                type=str,
                required=True,
                description="Model tag as shown by `ollama list`, e.g. llama3.1.",
            ),
            "base_url": FieldSpec(
                type=str,
                default="http://localhost:11434/v1",
                description="OpenAI-compatible endpoint exposed by Ollama.",
            ),
            "temperature": FieldSpec(
                type=float,
                default=0.7,
                description="Sampling temperature.",
            ),
        },
    ),
}

TTS_PROVIDERS: dict[str, ProviderSpec] = {
    "elevenlabs": ProviderSpec(
        name="elevenlabs",
        label="ElevenLabs",
        credential="ELEVEN_API_KEY",
        fields={
            "voice_id": FieldSpec(
                type=str,
                default=DEFAULT_ELEVENLABS_VOICE,
                description="ElevenLabs voice id. Blank uses the stock Rachel voice.",
            ),
            "model": FieldSpec(
                type=str,
                default="eleven_flash_v2_5",
                choices=("eleven_flash_v2_5", "eleven_turbo_v2_5"),
                description="Lowest-latency model first.",
            ),
        },
    ),
    "deepgram": ProviderSpec(
        name="deepgram",
        label="Deepgram Aura",
        credential="DEEPGRAM_API_KEY",
        fields={
            "model": FieldSpec(
                type=str,
                default=DEEPGRAM_VOICES[0],
                choices=DEEPGRAM_VOICES,
                description="Deepgram Aura-2 voice.",
            ),
        },
    ),
}

VAD_PROVIDERS: dict[str, ProviderSpec] = {
    "silero": ProviderSpec(
        name="silero",
        label="Silero",
        credential=None,
        fields={},
    ),
}

# Stage name -> catalogue. Iterated by the validator and by the /providers endpoint.
STAGES: dict[str, dict[str, ProviderSpec]] = {
    "stt": STT_PROVIDERS,
    "llm": LLM_PROVIDERS,
    "tts": TTS_PROVIDERS,
    "vad": VAD_PROVIDERS,
}


def describe_stages() -> dict[str, Any]:
    """Serialise the catalogue for the UI.

    This is the hand-rolled stand-in for pydantic's `model_json_schema()`. When
    pydantic lands, this function's body changes and its output shape does not.
    """
    out: dict[str, Any] = {}
    for stage, catalogue in STAGES.items():
        out[stage] = [
            {
                "name": spec.name,
                "label": spec.label,
                "credential": spec.credential,
                "fields": [
                    {
                        "name": fname,
                        "type": fspec.type.__name__,
                        "required": fspec.required,
                        "default": fspec.default,
                        "choices": list(fspec.choices) if fspec.choices else None,
                        "description": fspec.description,
                    }
                    for fname, fspec in spec.fields.items()
                ],
            }
            for spec in catalogue.values()
        ]
    return out
