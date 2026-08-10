"""Turning a validated config into live LiveKit components.

A registry, not an if/elif chain. Each provider gets a builder registered against
the same name it uses in `config/providers.py`, so adding a provider is one table
entry plus one function here — no existing code is edited.

Every plugin is imported at module level, and it has to be. LiveKit plugins call
`Plugin.register_plugin()` at import, which raises "Plugins must be registered on
the main thread" if it happens anywhere else — and builders run inside the job
runner thread. Importing lazily inside the builders looks tidier and crashes the
first time a session starts.

The cost is that starting the worker loads onnxruntime, google-genai and grpc
whether or not this config uses them. That is the price of the constraint above.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from livekit.agents import llm as lk_llm
from livekit.agents import stt as lk_stt
from livekit.agents import tts as lk_tts
from livekit.agents import vad as lk_vad

# Must be module level -- see the note at the top of this file.
from livekit.plugins import deepgram as lk_deepgram
from livekit.plugins import elevenlabs as lk_elevenlabs
from livekit.plugins import google as lk_google
from livekit.plugins import openai as lk_openai
from livekit.plugins import silero as lk_silero

from voice_agent.config.providers import STAGES
from voice_agent.config.schema import StageConfig

type Builder[T] = Callable[[StageConfig], T]

# The plugin base classes are generic; nothing here cares about the parameter.
type STT = lk_stt.STT[Any]
type LLM = lk_llm.LLM[Any]
type TTS = lk_tts.TTS[Any]
type VAD = lk_vad.VAD

_STT_BUILDERS: dict[str, Builder[STT]] = {}
_LLM_BUILDERS: dict[str, Builder[LLM]] = {}
_TTS_BUILDERS: dict[str, Builder[TTS]] = {}
_VAD_BUILDERS: dict[str, Builder[VAD]] = {}

BUILDERS: dict[str, dict[str, Builder[Any]]] = {
    "stt": _STT_BUILDERS,
    "llm": _LLM_BUILDERS,
    "tts": _TTS_BUILDERS,
    "vad": _VAD_BUILDERS,
}


class UnsupportedProviderError(ValueError):
    """No builder registered for a provider the config asked for."""


def _register[T](
    registry: dict[str, Builder[T]], name: str
) -> Callable[[Builder[T]], Builder[T]]:
    def decorator(fn: Builder[T]) -> Builder[T]:
        registry[name] = fn
        return fn

    return decorator


def register_stt(name: str) -> Callable[[Builder[STT]], Builder[STT]]:
    return _register(_STT_BUILDERS, name)


def register_llm(name: str) -> Callable[[Builder[LLM]], Builder[LLM]]:
    return _register(_LLM_BUILDERS, name)


def register_tts(name: str) -> Callable[[Builder[TTS]], Builder[TTS]]:
    return _register(_TTS_BUILDERS, name)


def register_vad(name: str) -> Callable[[Builder[VAD]], Builder[VAD]]:
    return _register(_VAD_BUILDERS, name)


def _build[T](stage: str, registry: dict[str, Builder[T]], cfg: StageConfig) -> T:
    builder = registry.get(cfg.provider)
    if builder is None:
        known = ", ".join(sorted(registry)) or "none"
        raise UnsupportedProviderError(
            f"no {stage} builder registered for {cfg.provider!r}; registered: {known}"
        )
    return builder(cfg)


# --- STT ------------------------------------------------------------------------


@register_stt("deepgram")
def _deepgram_stt(cfg: StageConfig) -> STT:
    return lk_deepgram.STT(
        model=str(cfg.options["model"]),
        language=str(cfg.options["language"]),
    )


# --- LLM ------------------------------------------------------------------------


@register_llm("google")
def _google_llm(cfg: StageConfig) -> LLM:
    return lk_google.LLM(
        model=str(cfg.options["model"]),
        temperature=float(cfg.options["temperature"]),
    )


@register_llm("ollama")
def _ollama_llm(cfg: StageConfig) -> LLM:
    return lk_openai.LLM.with_ollama(
        model=str(cfg.options["model"]),
        base_url=str(cfg.options["base_url"]),
        temperature=float(cfg.options["temperature"]),
    )


# --- TTS ------------------------------------------------------------------------


@register_tts("elevenlabs")
def _elevenlabs_tts(cfg: StageConfig) -> TTS:
    return lk_elevenlabs.TTS(
        voice_id=str(cfg.options["voice_id"]),
        model=str(cfg.options["model"]),
    )


@register_tts("deepgram")
def _deepgram_tts(cfg: StageConfig) -> TTS:
    return lk_deepgram.TTS(model=str(cfg.options["model"]))


# --- VAD ------------------------------------------------------------------------


@register_vad("silero")
def _silero_vad(_cfg: StageConfig) -> VAD:
    return lk_silero.VAD.load()


# --- public API -----------------------------------------------------------------


def build_stt(cfg: StageConfig) -> STT:
    return _build("stt", _STT_BUILDERS, cfg)


def build_llm(cfg: StageConfig) -> LLM:
    return _build("llm", _LLM_BUILDERS, cfg)


def build_tts(cfg: StageConfig) -> TTS:
    return _build("tts", _TTS_BUILDERS, cfg)


def build_vad(cfg: StageConfig) -> VAD:
    return _build("vad", _VAD_BUILDERS, cfg)


def unregistered_providers() -> dict[str, list[str]]:
    """Providers in the catalogue with no builder here.

    Guards the one coupling in this design: the names in `config/providers.py` and
    the names registered above have to stay in step. A test asserts this is empty.
    """
    return {
        stage: sorted(set(catalogue) - set(BUILDERS[stage]))
        for stage, catalogue in STAGES.items()
        if set(catalogue) - set(BUILDERS[stage])
    }
