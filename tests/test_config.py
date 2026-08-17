import json
from pathlib import Path

import pytest

from voice_agent.config import (
    AgentConfig,
    ConfigStore,
    ConfigValidationError,
    describe_stages,
    parse_config,
)
from voice_agent.config.env import missing_credentials
from voice_agent.config.providers import DEFAULT_ELEVENLABS_VOICE
from voice_agent.config.store import ConfigNotFoundError, make_config_id, slugify

SAMPLE = Path("configs/sample-agent-20260809-132143.json")


def sample_dict():
    return json.loads(SAMPLE.read_text())


def locs(exc):
    return {e.loc for e in exc.value.errors}


# --- the sample file is the reference shape -------------------------------------


def test_sample_file_parses_unchanged():
    config = parse_config(sample_dict())
    assert config.name == "sample-agent"
    assert config.stt.provider == "deepgram"
    assert config.llm.provider == "google"
    assert config.llm.options["model"] == "gemini-3.5-flash-lite"
    assert config.tts.provider == "elevenlabs"
    assert config.vad.provider == "silero"
    assert config.tools == ()
    assert "voice assistant" in config.prompt.instructions


def test_sample_file_round_trips():
    assert parse_config(sample_dict()).to_dict() == sample_dict()


# --- validation -----------------------------------------------------------------


def test_unknown_provider_names_the_valid_ones():
    raw = sample_dict()
    raw["tts"]["provider"] = "cartesia"
    with pytest.raises(ConfigValidationError) as exc:
        parse_config(raw)
    assert ("tts", "provider") in locs(exc)
    assert "elevenlabs" in str(exc.value)


def test_missing_required_field():
    raw = sample_dict()
    raw["llm"] = {"provider": "ollama"}  # model is required, base_url is not
    with pytest.raises(ConfigValidationError) as exc:
        parse_config(raw)
    assert ("llm", "model") in locs(exc)


def test_unknown_field_is_rejected():
    raw = sample_dict()
    raw["stt"]["modle"] = "nova-3"
    with pytest.raises(ConfigValidationError) as exc:
        parse_config(raw)
    assert ("stt", "modle") in locs(exc)


def test_field_from_another_provider_is_rejected():
    raw = sample_dict()
    raw["llm"]["voice_id"] = "abc"
    with pytest.raises(ConfigValidationError) as exc:
        parse_config(raw)
    assert ("llm", "voice_id") in locs(exc)


def test_wrong_type_is_reported():
    raw = sample_dict()
    raw["llm"]["temperature"] = "hot"
    with pytest.raises(ConfigValidationError) as exc:
        parse_config(raw)
    assert ("llm", "temperature") in locs(exc)


def test_value_outside_choices_is_rejected():
    raw = sample_dict()
    raw["llm"]["model"] = "gemini-3-ultra"
    with pytest.raises(ConfigValidationError) as exc:
        parse_config(raw)
    assert ("llm", "model") in locs(exc)


def test_empty_prompt_is_rejected():
    raw = sample_dict()
    raw["prompt"]["instructions"] = "   "
    with pytest.raises(ConfigValidationError) as exc:
        parse_config(raw)
    assert ("prompt", "instructions") in locs(exc)


def test_every_error_is_reported_not_just_the_first():
    raw = sample_dict()
    raw["name"] = ""
    raw["stt"]["language"] = "klingon"
    raw["llm"]["model"] = "nope"
    with pytest.raises(ConfigValidationError) as exc:
        parse_config(raw)
    assert {("name",), ("stt", "language"), ("llm", "model")} <= locs(exc)


def test_defaults_are_filled_in():
    raw = sample_dict()
    del raw["stt"]["language"]
    del raw["llm"]["temperature"]
    config = parse_config(raw)
    assert config.stt.options["language"] == "en"
    assert config.llm.options["temperature"] == 0.7


def test_ollama_is_a_valid_llm():
    raw = sample_dict()
    raw["llm"] = {"provider": "ollama", "model": "llama3.1"}
    config = parse_config(raw)
    assert config.llm.options["base_url"] == "http://localhost:11434/v1"


def test_deepgram_is_a_valid_tts():
    raw = sample_dict()
    raw["tts"] = {"provider": "deepgram"}
    config = parse_config(raw)
    assert config.tts.options["model"] == "aura-2-thalia-en"


def test_elevenlabs_voice_id_is_optional_and_defaults():
    raw = sample_dict()
    del raw["tts"]["voice_id"]
    assert parse_config(raw).tts.options["voice_id"] == DEFAULT_ELEVENLABS_VOICE


def test_blank_optional_field_falls_back_to_the_default():
    """A cleared form field arrives as "" and must not reach the provider."""
    raw = sample_dict()
    raw["tts"]["voice_id"] = "   "
    assert parse_config(raw).tts.options["voice_id"] == DEFAULT_ELEVENLABS_VOICE


def test_blank_number_field_falls_back_to_the_default():
    raw = sample_dict()
    raw["llm"]["temperature"] = ""
    assert parse_config(raw).llm.options["temperature"] == 0.7


def test_blank_required_field_is_rejected():
    raw = sample_dict()
    raw["llm"] = {"provider": "ollama", "model": "  "}
    with pytest.raises(ConfigValidationError) as exc:
        parse_config(raw)
    assert locs(exc) == {("llm", "model")}


def test_stt_language_is_a_fixed_set():
    raw = sample_dict()
    raw["stt"]["language"] = "klingon"
    with pytest.raises(ConfigValidationError) as exc:
        parse_config(raw)
    assert ("stt", "language") in locs(exc)


def test_stt_language_accepts_multi():
    raw = sample_dict()
    raw["stt"]["language"] = "multi"
    assert parse_config(raw).stt.options["language"] == "multi"


def test_missing_stage_is_reported():
    raw = sample_dict()
    del raw["vad"]
    with pytest.raises(ConfigValidationError) as exc:
        parse_config(raw)
    assert ("vad",) in locs(exc)


# --- store ----------------------------------------------------------------------


def test_slugify():
    assert slugify("My Sales Agent!") == "my-sales-agent"
    assert slugify("  ") == "agent"


def test_config_id_carries_name_date_and_time():
    config_id = make_config_id("My Sales Agent")
    slug, date, time = config_id.rsplit("-", 2)
    assert slug == "my-sales-agent"
    assert len(date) == 8 and date.isdigit()
    assert len(time) == 6 and time.isdigit()


def test_save_stamps_id_and_created_at(tmp_path: Path):
    store = ConfigStore(tmp_path)
    saved = store.save(parse_config(sample_dict()))
    assert saved.id.startswith("sample-agent-")
    assert saved.created_at.endswith("Z")
    assert (tmp_path / f"{saved.id}.json").is_file()


def test_two_saves_in_the_same_second_do_not_collide(tmp_path: Path):
    store = ConfigStore(tmp_path)
    config = parse_config(sample_dict())
    first = store.save(config)
    second = store.save(config)
    assert first.id != second.id
    assert len(list(tmp_path.glob("*.json"))) == 2


def test_save_then_load_round_trips(tmp_path: Path):
    store = ConfigStore(tmp_path)
    saved = store.save(parse_config(sample_dict()))
    assert store.load(saved.id) == saved


def test_saved_file_is_valid_on_disk(tmp_path: Path):
    store = ConfigStore(tmp_path)
    saved = store.save(parse_config(sample_dict()))
    on_disk = json.loads((tmp_path / f"{saved.id}.json").read_text())
    assert parse_config(on_disk) == saved


def test_load_missing_config_raises(tmp_path: Path):
    with pytest.raises(ConfigNotFoundError):
        ConfigStore(tmp_path).load("nope-20260101-000000")


def test_list_is_newest_first_and_skips_invalid(tmp_path: Path):
    store = ConfigStore(tmp_path)
    raw = sample_dict()
    older = AgentConfig(
        id="",
        name="older",
        created_at="",
        stt=parse_config(raw).stt,
        llm=parse_config(raw).llm,
        tts=parse_config(raw).tts,
        vad=parse_config(raw).vad,
        prompt=parse_config(raw).prompt,
    )
    store.save(older)
    store.save(parse_config(raw))
    (tmp_path / "broken.json").write_text("{ not json")

    listed = store.list()
    assert len(listed) == 2
    assert listed[0].id > listed[1].id


def test_invalid_json_reports_the_file(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ oops")
    with pytest.raises(ConfigValidationError) as exc:
        ConfigStore(tmp_path).load_file(bad)
    assert "invalid JSON" in str(exc.value)


def test_list_of_empty_dir_is_empty(tmp_path: Path):
    assert ConfigStore(tmp_path / "nothing-here").list() == []


# --- catalogue / credentials ----------------------------------------------------


def test_describe_stages_covers_every_stage():
    described = describe_stages()
    assert set(described) == {"stt", "llm", "tts", "vad"}
    llm_names = {p["name"] for p in described["llm"]}
    assert llm_names == {"google", "ollama"}


def test_describe_stages_exposes_fields_for_the_ui():
    tts = {p["name"]: p for p in describe_stages()["tts"]}
    voice = {f["name"]: f for f in tts["elevenlabs"]["fields"]}
    assert voice["voice_id"]["required"] is False
    assert voice["voice_id"]["default"] == DEFAULT_ELEVENLABS_VOICE
    assert voice["model"]["choices"] == [
        "eleven_flash_v2_5",
        "eleven_turbo_v2_5",
    ]


def test_stt_language_is_offered_as_a_fixed_list():
    stt = {p["name"]: p for p in describe_stages()["stt"]}
    language = {f["name"]: f for f in stt["deepgram"]["fields"]}["language"]
    assert language["default"] == "en"
    assert "multi" in language["choices"]
    assert "en-IN" in language["choices"]


def test_missing_credentials_lists_what_is_needed(monkeypatch):
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("ELEVEN_API_KEY", "x")
    config = parse_config(sample_dict())
    assert missing_credentials(config) == ["DEEPGRAM_API_KEY", "GOOGLE_API_KEY"]


def test_no_missing_credentials_when_all_present(monkeypatch):
    for var in ("DEEPGRAM_API_KEY", "GOOGLE_API_KEY", "ELEVEN_API_KEY"):
        monkeypatch.setenv(var, "x")
    assert missing_credentials(parse_config(sample_dict())) == []


def test_ollama_needs_no_credential(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    for var in ("DEEPGRAM_API_KEY", "ELEVEN_API_KEY"):
        monkeypatch.setenv(var, "x")
    raw = sample_dict()
    raw["llm"] = {"provider": "ollama", "model": "llama3.1"}
    assert missing_credentials(parse_config(raw)) == []
