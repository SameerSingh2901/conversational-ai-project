import json
from pathlib import Path

import pytest

from voice_agent import pipeline
from voice_agent.config.providers import STAGES
from voice_agent.config.schema import StageConfig, parse_config
from voice_agent.pipeline import UnsupportedProviderError
from voice_agent.tools.registry import (
    TOOLS,
    UnknownToolError,
    register_tool,
    resolve_tools,
)

SAMPLE = Path("configs/sample-agent-20260809-132143.json")


@pytest.fixture
def sample_config():
    return parse_config(json.loads(SAMPLE.read_text()))


# --- the coupling this design has to keep honest ---------------------------------


def test_every_catalogue_provider_has_a_builder():
    """The one place providers.py and pipeline.py can drift apart."""
    assert pipeline.unregistered_providers() == {}


def test_every_builder_has_a_catalogue_entry():
    """And the reverse: a builder nobody can select is dead code."""
    orphans = {
        stage: sorted(set(builders) - set(STAGES[stage]))
        for stage, builders in pipeline.BUILDERS.items()
        if set(builders) - set(STAGES[stage])
    }
    assert orphans == {}


def test_registered_provider_names_match_expectations():
    assert set(pipeline.BUILDERS["llm"]) == {"google", "ollama"}
    assert set(pipeline.BUILDERS["tts"]) == {"elevenlabs", "deepgram"}
    assert set(pipeline.BUILDERS["stt"]) == {"deepgram"}
    assert set(pipeline.BUILDERS["vad"]) == {"silero"}


def test_plugins_are_imported_at_module_level():
    """LiveKit registers plugins at import and refuses to do it off the main thread.

    Builders run inside the job runner thread, so a lazy `from livekit.plugins
    import x` inside a builder raises "Plugins must be registered on the main
    thread" the first time a session starts. Importing `pipeline` must be enough
    to have registered every plugin.
    """
    import sys

    for plugin in ("deepgram", "elevenlabs", "google", "openai", "silero"):
        assert f"livekit.plugins.{plugin}" in sys.modules, (
            f"{plugin} is not imported at pipeline module level"
        )


def test_no_builder_imports_a_plugin_lazily():
    """Belt and braces: catch the lazy import in source, not just in effect."""
    source = Path("src/voice_agent/pipeline.py").read_text()
    body = source.split("# --- STT")[1]
    assert "from livekit.plugins" not in body, (
        "plugin imports must stay at module level, not inside builders"
    )


# --- dispatch --------------------------------------------------------------------


@pytest.mark.parametrize(
    "build, stage",
    [
        (pipeline.build_stt, "stt"),
        (pipeline.build_llm, "llm"),
        (pipeline.build_tts, "tts"),
        (pipeline.build_vad, "vad"),
    ],
)
def test_unregistered_provider_raises_and_lists_what_exists(build, stage):
    with pytest.raises(UnsupportedProviderError) as exc:
        build(StageConfig(provider="nope", options={}))
    assert stage in str(exc.value)
    assert "registered:" in str(exc.value)


def test_builders_receive_the_options_from_the_config(monkeypatch, sample_config):
    """Dispatch passes the right StageConfig through without touching the network."""
    seen = {}
    sentinel = object()

    @pipeline.register_llm("fake-for-test")
    def _fake(cfg):
        seen["provider"] = cfg.provider
        seen["model"] = cfg.options["model"]
        return sentinel

    try:
        result = pipeline.build_llm(
            StageConfig(provider="fake-for-test", options={"model": "x"})
        )
        assert result is sentinel
        assert seen == {"provider": "fake-for-test", "model": "x"}
    finally:
        del pipeline.BUILDERS["llm"]["fake-for-test"]


def test_sample_config_selects_registered_providers(sample_config):
    for stage in ("stt", "llm", "tts", "vad"):
        provider = getattr(sample_config, stage).provider
        assert provider in pipeline.BUILDERS[stage]


# --- tool registry ---------------------------------------------------------------


def test_empty_tool_list_resolves_to_nothing():
    assert resolve_tools([]) == []


def test_unknown_tool_raises_with_a_useful_message():
    with pytest.raises(UnknownToolError) as exc:
        resolve_tools(["property_search"])
    assert "property_search" in str(exc.value)


def test_registered_tool_resolves():
    @register_tool("test-tool")
    def _tool():
        return 42

    try:
        assert resolve_tools(["test-tool"]) == [_tool]
    finally:
        del TOOLS["test-tool"]


def test_tool_order_follows_the_config():
    @register_tool("a")
    def _a():
        pass

    @register_tool("b")
    def _b():
        pass

    try:
        assert resolve_tools(["b", "a"]) == [_b, _a]
    finally:
        del TOOLS["a"], TOOLS["b"]
