import base64
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from livekit import api as livekit_api

from voice_agent.agent import config_from_metadata, room_metadata
from voice_agent.api.app import create_app
from voice_agent.config.env import LiveKitCredentials, livekit_credentials
from voice_agent.config.errors import ConfigValidationError

SAMPLE = Path("configs/sample-agent-20260809-132143.json")

FAKE_LIVEKIT = {
    "LIVEKIT_URL": "wss://test.livekit.cloud",
    "LIVEKIT_API_KEY": "APItestkey",
    "LIVEKIT_API_SECRET": "s" * 32,
}


@pytest.fixture
def sample():
    return json.loads(SAMPLE.read_text())


@pytest.fixture
def creds(monkeypatch):
    for var, value in FAKE_LIVEKIT.items():
        monkeypatch.setenv(var, value)
    for var in ("DEEPGRAM_API_KEY", "GOOGLE_API_KEY", "ELEVEN_API_KEY"):
        monkeypatch.setenv(var, "x")


@pytest.fixture
def client(tmp_path: Path):
    with TestClient(create_app(config_dir=tmp_path)) as client:
        yield client


@pytest.fixture
def saved(client, sample, creds):
    return client.post("/api/configs", json=sample).json()


def jwt_payload(token: str) -> dict[str, Any]:
    body = token.split(".")[1]
    body += "=" * (-len(body) % 4)
    return json.loads(base64.urlsafe_b64decode(body))


# --- credentials helper ----------------------------------------------------------


def test_livekit_credentials_read_from_env(creds):
    got = livekit_credentials()
    assert got.url == "wss://test.livekit.cloud"
    assert got.api_key == "APItestkey"


def test_ws_url_becomes_http_for_the_server_api():
    assert (
        LiveKitCredentials("wss://x.livekit.cloud", "k", "s").http_url
        == "https://x.livekit.cloud"
    )
    assert LiveKitCredentials("ws://localhost:7880", "k", "s").http_url == (
        "http://localhost:7880"
    )
    assert LiveKitCredentials("https://already", "k", "s").http_url == "https://already"


# --- the sessions route ----------------------------------------------------------


@pytest.fixture
def captured_room(monkeypatch):
    """Stub out LiveKit's server API so the happy path runs with no network."""
    captured = {}

    class FakeRoomService:
        async def create_room(self, request):
            captured["name"] = request.name
            captured["metadata"] = request.metadata
            captured["empty_timeout"] = request.empty_timeout

    class FakeLiveKitAPI:
        def __init__(self, url, api_key, api_secret):
            captured["url"] = url
            self.room = FakeRoomService()

        async def aclose(self):
            captured["closed"] = True

    # sessions.py does `from livekit import api` and calls `api.LiveKitAPI(...)`,
    # so patching the attribute on the shared module reaches it.
    monkeypatch.setattr(livekit_api, "LiveKitAPI", FakeLiveKitAPI)
    return captured


def test_session_returns_url_token_and_room(client, saved, creds, captured_room):
    response = client.post("/api/sessions", json={"config_id": saved["id"]})
    assert response.status_code == 201
    body = response.json()
    assert body["url"] == "wss://test.livekit.cloud"
    assert body["room"].startswith(saved["id"])
    assert body["config_name"] == "sample-agent"
    assert body["token"]


def test_the_room_carries_the_whole_config_as_metadata(
    client, saved, creds, captured_room, sample
):
    """This is the contract the worker depends on."""
    client.post("/api/sessions", json={"config_id": saved["id"]})
    carried = config_from_metadata(captured_room["metadata"])
    assert carried is not None
    assert carried.id == saved["id"]
    assert carried.prompt.instructions == sample["prompt"]["instructions"]
    assert carried.llm.options["model"] == "gemini-3.5-flash-lite"


def test_server_api_is_called_over_https_not_wss(client, saved, creds, captured_room):
    client.post("/api/sessions", json={"config_id": saved["id"]})
    assert captured_room["url"] == "https://test.livekit.cloud"
    assert captured_room["closed"] is True


def test_token_grants_join_on_that_room_only(client, saved, creds, captured_room):
    body = client.post("/api/sessions", json={"config_id": saved["id"]}).json()
    grants = jwt_payload(body["token"])["video"]
    assert grants["room"] == body["room"]
    assert grants["roomJoin"] is True
    assert grants["canPublish"] is True


def test_each_call_gets_its_own_room(client, saved, creds, captured_room):
    first = client.post("/api/sessions", json={"config_id": saved["id"]}).json()
    second = client.post("/api/sessions", json={"config_id": saved["id"]}).json()
    assert first["room"] != second["room"]


def test_config_id_is_required(client, creds):
    assert client.post("/api/sessions", json={}).status_code == 422


def test_unknown_config_is_404(client, creds):
    response = client.post("/api/sessions", json={"config_id": "nope-20260101-000000"})
    assert response.status_code == 404


def test_missing_provider_credentials_is_400(client, sample, monkeypatch):
    for var, value in FAKE_LIVEKIT.items():
        monkeypatch.setenv(var, value)
    monkeypatch.setenv("DEEPGRAM_API_KEY", "x")
    monkeypatch.setenv("GOOGLE_API_KEY", "x")
    monkeypatch.setenv("ELEVEN_API_KEY", "x")
    saved = client.post("/api/configs", json=sample).json()

    monkeypatch.delenv("ELEVEN_API_KEY")
    response = client.post("/api/sessions", json={"config_id": saved["id"]})
    assert response.status_code == 400
    assert "ELEVEN_API_KEY" in response.json()["detail"]


def test_missing_livekit_credentials_is_400(client, sample, monkeypatch):
    for var in ("DEEPGRAM_API_KEY", "GOOGLE_API_KEY", "ELEVEN_API_KEY"):
        monkeypatch.setenv(var, "x")
    saved = client.post("/api/configs", json=sample).json()

    monkeypatch.delenv("LIVEKIT_API_KEY", raising=False)
    response = client.post("/api/sessions", json={"config_id": saved["id"]})
    assert response.status_code == 400
    assert "LIVEKIT_API_KEY" in response.json()["detail"]


# --- room metadata: the contract between API and worker --------------------------


def test_metadata_round_trips_into_a_config(sample):
    """What the API writes onto the room is exactly what the worker can parse."""
    metadata = json.dumps(sample)
    config = config_from_metadata(metadata)
    assert config is not None
    assert config.llm.provider == "google"
    assert config.prompt.instructions == sample["prompt"]["instructions"]


def test_no_metadata_falls_back_to_the_env_var():
    assert config_from_metadata(None) is None
    assert config_from_metadata("") is None
    assert config_from_metadata("   ") is None


def test_metadata_from_something_else_is_ignored():
    """A room created by another tool must not break our worker."""
    assert config_from_metadata('{"some":"other tool"}') is None
    assert config_from_metadata("not json at all") is None
    assert config_from_metadata("[1,2,3]") is None


def md(ctx: Any) -> str | None:
    """`room_metadata` duck-types its argument; the fakes below are not JobContexts."""
    return room_metadata(ctx)


class FakeRoom:
    def __init__(self, metadata=""):
        self.metadata = metadata


class FakeJob:
    def __init__(self, metadata=""):
        self.room = FakeRoom(metadata)


class FakeCtx:
    def __init__(self, job_metadata="", room_metadata=""):
        self.job = FakeJob(job_metadata)
        self.room = FakeRoom(room_metadata)


def test_metadata_comes_from_the_job_assignment():
    """`ctx.room` is not connected in the entrypoint, so its metadata is empty.

    Reading it there is what made every UI-started call crash: the room record
    only reaches us through the job assignment at that point.
    """
    ctx = FakeCtx(job_metadata='{"from":"job"}', room_metadata="")
    assert md(ctx) == '{"from":"job"}'


def test_room_metadata_is_the_fallback():
    ctx = FakeCtx(job_metadata="", room_metadata='{"from":"room"}')
    assert md(ctx) == '{"from":"room"}'


def test_no_metadata_anywhere_is_none():
    assert md(FakeCtx()) is None
    assert md(FakeCtx(job_metadata="   ")) is None


def test_job_metadata_wins_over_room():
    ctx = FakeCtx(job_metadata='{"from":"job"}', room_metadata='{"from":"room"}')
    assert md(ctx) == '{"from":"job"}'


def test_metadata_that_is_ours_but_invalid_raises(sample):
    """Silently ignoring it would start the call with the wrong agent."""
    del sample["llm"]
    with pytest.raises(ConfigValidationError):
        config_from_metadata(json.dumps(sample))
