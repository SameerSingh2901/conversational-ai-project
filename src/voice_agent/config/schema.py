"""The agent config document: dataclasses plus hand-rolled validation.

`parse_config()` is the only way a raw JSON dict becomes an `AgentConfig`. Every
caller downstream — the pipeline, the API, the worker — receives an already-valid
object and never inspects raw dicts. That single choke point is what makes this
swappable for pydantic later without touching anything else.

Field rules come from `providers.py`, so validation and the UI can never disagree
about which providers exist or what they need.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from voice_agent.config.errors import ConfigValidationError, FieldError
from voice_agent.config.providers import STAGES, ProviderSpec

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class StageConfig:
    """One pipeline stage: which provider, and that provider's own options."""

    provider: str
    options: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"provider": self.provider, **dict(self.options)}


@dataclass(frozen=True)
class PromptConfig:
    instructions: str
    greeting: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"instructions": self.instructions, "greeting": self.greeting}


@dataclass(frozen=True)
class AgentConfig:
    """A complete, validated agent definition."""

    id: str
    name: str
    created_at: str
    stt: StageConfig
    llm: StageConfig
    tts: StageConfig
    vad: StageConfig
    prompt: PromptConfig
    tools: tuple[str, ...] = ()
    version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        """Serialise back to the on-disk JSON shape, key order included."""
        return {
            "version": self.version,
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at,
            "stt": self.stt.to_dict(),
            "llm": self.llm.to_dict(),
            "tts": self.tts.to_dict(),
            "vad": self.vad.to_dict(),
            "prompt": self.prompt.to_dict(),
            "tools": list(self.tools),
        }


def _type_name(expected: type) -> str:
    return expected.__name__


def _matches_type(value: object, expected: type) -> bool:
    # bool is a subclass of int in Python; a boolean is never a valid number here.
    if isinstance(value, bool) and expected is not bool:
        return False
    if expected is float:
        return isinstance(value, (int, float))
    return isinstance(value, expected)


def _coerce(value: object, expected: type) -> Any:
    if expected is float and isinstance(value, int):
        return float(value)
    return value


def _require_str(
    raw: Mapping[str, Any],
    key: str,
    errors: list[FieldError],
    *,
    allow_empty: bool = False,
) -> str:
    value = raw.get(key)
    if value is None:
        errors.append(FieldError((key,), "field required"))
        return ""
    if not isinstance(value, str):
        errors.append(FieldError((key,), f"expected str, got {type(value).__name__}"))
        return ""
    if not allow_empty and not value.strip():
        errors.append(FieldError((key,), "must not be empty"))
        return ""
    return value


def _parse_stage(
    raw: object,
    stage: str,
    catalogue: Mapping[str, ProviderSpec],
    errors: list[FieldError],
) -> StageConfig:
    """Validate one stage against the catalogue of providers allowed for it."""
    if not isinstance(raw, dict):
        errors.append(FieldError((stage,), "expected an object"))
        return StageConfig(provider="")

    data: dict[str, Any] = dict(raw)
    provider = data.pop("provider", None)

    if provider is None:
        errors.append(FieldError((stage, "provider"), "field required"))
        return StageConfig(provider="")
    if not isinstance(provider, str) or provider not in catalogue:
        valid = ", ".join(sorted(catalogue))
        errors.append(
            FieldError(
                (stage, "provider"),
                f"unknown provider {provider!r}; expected one of: {valid}",
            )
        )
        return StageConfig(provider="")

    spec = catalogue[provider]
    options: dict[str, Any] = {}

    for fname, fspec in spec.fields.items():
        loc = (stage, fname)
        if fname not in data:
            if fspec.required:
                errors.append(FieldError(loc, "field required"))
            else:
                options[fname] = fspec.default
            continue

        value = data.pop(fname)

        # A cleared form field arrives as "". Treat it as "not supplied": fall back
        # to the default, or complain if the field is genuinely required. Without
        # this an empty string sails through and fails later at the provider's API.
        if isinstance(value, str) and not value.strip():
            if fspec.required:
                errors.append(FieldError(loc, "must not be empty"))
            else:
                options[fname] = fspec.default
            continue

        if not _matches_type(value, fspec.type):
            errors.append(
                FieldError(
                    loc,
                    f"expected {_type_name(fspec.type)}, got {type(value).__name__}",
                )
            )
            continue
        if fspec.choices is not None and value not in fspec.choices:
            allowed = ", ".join(fspec.choices)
            errors.append(FieldError(loc, f"expected one of: {allowed}"))
            continue
        options[fname] = _coerce(value, fspec.type)

    # Anything left over is a typo or a field belonging to a different provider.
    for leftover in sorted(data):
        errors.append(
            FieldError(
                (stage, leftover),
                f"unknown field for provider {provider!r}",
            )
        )

    return StageConfig(provider=provider, options=options)


def _parse_prompt(raw: object, errors: list[FieldError]) -> PromptConfig:
    if not isinstance(raw, dict):
        errors.append(FieldError(("prompt",), "expected an object"))
        return PromptConfig(instructions="")

    data: dict[str, Any] = dict(raw)
    instructions = data.pop("instructions", None)
    if not isinstance(instructions, str) or not instructions.strip():
        errors.append(
            FieldError(("prompt", "instructions"), "field required, must not be empty")
        )
        instructions = ""

    greeting = data.pop("greeting", "")
    if not isinstance(greeting, str):
        errors.append(FieldError(("prompt", "greeting"), "expected str"))
        greeting = ""

    for leftover in sorted(data):
        errors.append(FieldError(("prompt", leftover), "unknown field"))

    return PromptConfig(instructions=instructions, greeting=greeting)


def _parse_tools(raw: object, errors: list[FieldError]) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        errors.append(FieldError(("tools",), "expected a list of tool names"))
        return ()
    names: list[str] = []
    for index, item in enumerate(raw):
        if not isinstance(item, str):
            errors.append(FieldError(("tools", str(index)), "expected str"))
            continue
        names.append(item)
    return tuple(names)


def parse_config(raw: object) -> AgentConfig:
    """Validate a raw JSON document and return an `AgentConfig`.

    Raises `ConfigValidationError` listing *every* problem found.
    """
    errors: list[FieldError] = []

    if not isinstance(raw, dict):
        raise ConfigValidationError([FieldError((), "expected a JSON object")])

    data: dict[str, Any] = dict(raw)

    version = data.get("version", SCHEMA_VERSION)
    if version != SCHEMA_VERSION:
        errors.append(
            FieldError(
                ("version",),
                f"unsupported version {version!r}; expected {SCHEMA_VERSION}",
            )
        )

    name = _require_str(data, "name", errors)
    # id and created_at are stamped by the store on save, so they may be absent
    # on a document that has not been saved yet.
    config_id = data.get("id", "")
    if not isinstance(config_id, str):
        errors.append(FieldError(("id",), "expected str"))
        config_id = ""
    created_at = data.get("created_at", "")
    if not isinstance(created_at, str):
        errors.append(FieldError(("created_at",), "expected str"))
        created_at = ""

    stages: dict[str, StageConfig] = {}
    for stage, catalogue in STAGES.items():
        if stage not in data:
            errors.append(FieldError((stage,), "field required"))
            stages[stage] = StageConfig(provider="")
            continue
        stages[stage] = _parse_stage(data[stage], stage, catalogue, errors)

    prompt = _parse_prompt(data.get("prompt"), errors)
    tools = _parse_tools(data.get("tools"), errors)

    known = {"version", "id", "name", "created_at", "prompt", "tools", *STAGES}
    for leftover in sorted(set(data) - known):
        errors.append(FieldError((leftover,), "unknown field"))

    if errors:
        raise ConfigValidationError(errors)

    return AgentConfig(
        id=config_id,
        name=name,
        created_at=created_at,
        stt=stages["stt"],
        llm=stages["llm"],
        tts=stages["tts"],
        vad=stages["vad"],
        prompt=prompt,
        tools=tools,
        version=SCHEMA_VERSION,
    )
