import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from voice_agent.api.app import create_app
from voice_agent.config.providers import DEFAULT_ELEVENLABS_VOICE

SAMPLE = Path("configs/sample-agent-20260809-132143.json")


@pytest.fixture
def sample():
    return json.loads(SAMPLE.read_text())


@pytest.fixture
def client(tmp_path: Path):
    with TestClient(create_app(config_dir=tmp_path)) as client:
        yield client


def errors_by_loc(response):
    return {tuple(e["loc"]): e["msg"] for e in response.json()["errors"]}


# --- health / providers ---------------------------------------------------------


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_providers_covers_every_stage(client):
    body = client.get("/api/providers").json()
    assert set(body) == {"stt", "llm", "tts", "vad"}
    assert {p["name"] for p in body["llm"]} == {"google", "ollama"}


def test_providers_report_availability(client, monkeypatch):
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    body = client.get("/api/providers").json()
    deepgram = next(p for p in body["stt"] if p["name"] == "deepgram")
    ollama = next(p for p in body["llm"] if p["name"] == "ollama")
    assert deepgram["available"] is False
    assert deepgram["credential"] == "DEEPGRAM_API_KEY"
    assert ollama["available"] is True  # local, needs no key


def test_providers_carry_the_fields_the_form_renders(client):
    body = client.get("/api/providers").json()
    elevenlabs = next(p for p in body["tts"] if p["name"] == "elevenlabs")
    fields = {f["name"]: f for f in elevenlabs["fields"]}
    assert fields["voice_id"]["required"] is False
    assert fields["voice_id"]["default"] == DEFAULT_ELEVENLABS_VOICE
    assert fields["model"]["default"] == "eleven_flash_v2_5"


# --- saving ---------------------------------------------------------------------


def test_save_returns_201_with_stamped_id(client, sample, tmp_path):
    response = client.post("/api/configs", json=sample)
    assert response.status_code == 201
    body = response.json()
    assert body["id"].startswith("sample-agent-")
    assert (tmp_path / f"{body['id']}.json").is_file()


def test_saved_file_matches_what_was_returned(client, sample, tmp_path):
    body = client.post("/api/configs", json=sample).json()
    on_disk = json.loads((tmp_path / f"{body['id']}.json").read_text())
    assert on_disk["prompt"]["instructions"] == sample["prompt"]["instructions"]
    assert on_disk["llm"]["model"] == "gemini-3.5-flash-lite"


def test_two_saves_make_two_files(client, sample):
    first = client.post("/api/configs", json=sample).json()["id"]
    sample["prompt"]["instructions"] = "A different prompt entirely."
    second = client.post("/api/configs", json=sample).json()["id"]
    assert first != second
    assert len(client.get("/api/configs").json()) == 2


def test_defaults_are_applied_on_save(client, sample):
    del sample["stt"]["language"]
    body = client.post("/api/configs", json=sample).json()
    assert body["stt"]["language"] == "en"


# --- validation errors ----------------------------------------------------------


def test_missing_required_field_is_422_with_loc(client, sample):
    sample["llm"] = {"provider": "ollama"}  # model is required
    response = client.post("/api/configs", json=sample)
    assert response.status_code == 422
    assert ("llm", "model") in errors_by_loc(response)


def test_blank_field_from_a_cleared_form_input_uses_the_default(client, sample):
    sample["tts"]["voice_id"] = ""
    body = client.post("/api/configs", json=sample).json()
    assert body["tts"]["voice_id"] == DEFAULT_ELEVENLABS_VOICE


def test_unknown_provider_is_422(client, sample):
    sample["tts"]["provider"] = "cartesia"
    response = client.post("/api/configs", json=sample)
    assert response.status_code == 422
    assert "elevenlabs" in errors_by_loc(response)[("tts", "provider")]


def test_all_errors_come_back_at_once(client, sample):
    sample["name"] = ""
    sample["prompt"]["instructions"] = ""
    sample["stt"]["language"] = "klingon"
    response = client.post("/api/configs", json=sample)
    assert {("name",), ("prompt", "instructions"), ("stt", "language")} <= set(
        errors_by_loc(response)
    )


def test_invalid_config_is_not_written_to_disk(client, sample, tmp_path):
    sample["stt"]["language"] = "klingon"
    client.post("/api/configs", json=sample)
    assert list(tmp_path.glob("*.json")) == []


def test_malformed_json_body_is_400(client):
    response = client.post(
        "/api/configs",
        content=b"{ not json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
    assert "invalid JSON" in response.json()["errors"][0]["msg"]


def test_validate_endpoint_does_not_save(client, sample, tmp_path):
    assert client.post("/api/configs/validate", json=sample).json()["valid"] is True
    assert list(tmp_path.glob("*.json")) == []


def test_validate_endpoint_reports_errors(client, sample):
    sample["llm"]["temperature"] = "hot"
    response = client.post("/api/configs/validate", json=sample)
    assert response.status_code == 422
    assert ("llm", "temperature") in errors_by_loc(response)


# --- listing and loading --------------------------------------------------------


def test_list_is_empty_to_begin_with(client):
    assert client.get("/api/configs").json() == []


def test_list_returns_summaries_not_whole_configs(client, sample):
    client.post("/api/configs", json=sample)
    [summary] = client.get("/api/configs").json()
    assert summary["name"] == "sample-agent"
    assert summary["llm"] == "google"
    assert "prompt" not in summary


def test_list_is_newest_first(client, sample):
    first = client.post("/api/configs", json=sample).json()["id"]
    sample["name"] = "zzz-later"
    second = client.post("/api/configs", json=sample).json()["id"]
    ids = [c["id"] for c in client.get("/api/configs").json()]
    assert set(ids) == {first, second}


def test_load_round_trips_through_the_api(client, sample):
    saved = client.post("/api/configs", json=sample).json()
    loaded = client.get(f"/api/configs/{saved['id']}").json()
    assert loaded["prompt"] == saved["prompt"]
    assert loaded["tts"]["voice_id"] == sample["tts"]["voice_id"]


def test_load_unknown_config_is_404(client):
    assert client.get("/api/configs/nope-20260101-000000").status_code == 404


def test_missing_credentials_are_reported(client, sample, monkeypatch):
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "x")
    monkeypatch.setenv("ELEVEN_API_KEY", "x")
    body = client.post("/api/configs", json=sample).json()
    assert body["missing_credentials"] == ["DEEPGRAM_API_KEY"]


# --- static UI ------------------------------------------------------------------


def test_ui_is_served_at_root(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Voice Agent" in response.text


def test_ui_assets_are_served(client):
    assert client.get("/app.js").status_code == 200
    assert client.get("/styles.css").status_code == 200


def test_api_routes_win_over_the_static_mount(client):
    assert client.get("/api/health").json()["status"] == "ok"
