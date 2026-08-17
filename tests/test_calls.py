"""Call records: the recorder's correlation, the store, and the read API.

Every event here is a stand-in — the point is that the recorder reads the fields
LiveKit actually publishes, and survives events that are malformed.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from voice_agent.agent import _RecordWriter
from voice_agent.api.app import create_app
from voice_agent.calls import CallRecorder, CallStore, record_from_dict
from voice_agent.calls.models import OUTCOME_COMPLETED, OUTCOME_ERROR
from voice_agent.calls.redaction import identity, redact, set_redactor
from voice_agent.calls.store import CallNotFoundError
from voice_agent.config import parse_config

SAMPLE = Path("configs/sample-agent-20260809-132143.json")
CALL_ID = "sample-agent-20260809-132143--abcd1234"


@pytest.fixture
def config():
    return parse_config(json.loads(SAMPLE.read_text()))


@pytest.fixture
def recorder(config):
    return CallRecorder(call_id=CALL_ID, config=config)


# --- stand-ins for the events LiveKit publishes ---------------------------------


@dataclass
class LLMMetrics:
    prompt_tokens: int = 0
    prompt_cached_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    type: str = "llm_metrics"


@dataclass
class TTSMetrics:
    characters_count: int = 0
    type: str = "tts_metrics"


@dataclass
class STTMetrics:
    audio_duration: float = 0.0
    type: str = "stt_metrics"


@dataclass
class MetricsEvent:
    metrics: Any


@dataclass
class Item:
    role: str


@dataclass
class ItemEvent:
    item: Any


@dataclass
class Call:
    name: str


@dataclass
class Output:
    name: str
    is_error: bool = False


@dataclass
class ToolsEvent:
    function_calls: Any
    function_call_outputs: Any


class FakeSession:
    """Captures handlers the way AgentSession.on would, so we can fire them."""

    def __init__(self):
        self.handlers: dict[str, Any] = {}

    def on(self, event, callback):
        self.handlers[event] = callback

    def fire(self, event, payload):
        self.handlers[event](payload)


# --- what the recorder collects -------------------------------------------------


def test_attach_subscribes_to_the_events_we_need(recorder):
    session = FakeSession()
    recorder.attach(session)
    assert set(session.handlers) == {
        "metrics_collected",
        "conversation_item_added",
        "function_tools_executed",
        "error",
    }


def test_token_usage_accumulates_across_llm_calls(recorder):
    """A turn that uses a tool makes two LLM calls; both must be counted."""
    session = FakeSession()
    recorder.attach(session)
    session.fire("metrics_collected", MetricsEvent(LLMMetrics(100, 10, 20, 120)))
    session.fire("metrics_collected", MetricsEvent(LLMMetrics(300, 0, 40, 340)))

    totals = recorder.finish().totals
    assert totals.llm_requests == 2
    assert totals.tokens.prompt_tokens == 400
    assert totals.tokens.prompt_cached_tokens == 10
    assert totals.tokens.completion_tokens == 60
    assert totals.tokens.total_tokens == 460


def test_tts_characters_and_stt_audio_accumulate(recorder):
    session = FakeSession()
    recorder.attach(session)
    session.fire("metrics_collected", MetricsEvent(TTSMetrics(characters_count=120)))
    session.fire("metrics_collected", MetricsEvent(TTSMetrics(characters_count=80)))
    session.fire("metrics_collected", MetricsEvent(STTMetrics(audio_duration=3.5)))
    session.fire("metrics_collected", MetricsEvent(STTMetrics(audio_duration=2.25)))

    totals = recorder.finish().totals
    assert totals.tts_characters == 200
    assert totals.stt_audio_seconds == pytest.approx(5.75)


def test_turns_are_counted_by_speaker(recorder):
    session = FakeSession()
    recorder.attach(session)
    for role in ("assistant", "user", "assistant", "user", "assistant"):
        session.fire("conversation_item_added", ItemEvent(Item(role)))

    record = recorder.finish()
    assert (record.user_turns, record.agent_turns) == (2, 3)


def test_tool_calls_and_errors_are_tallied(recorder):
    session = FakeSession()
    recorder.attach(session)
    session.fire(
        "function_tools_executed",
        ToolsEvent(
            [Call("knowledge_base"), Call("knowledge_base")], [Output("knowledge_base")]
        ),
    )
    session.fire(
        "function_tools_executed",
        ToolsEvent([Call("knowledge_base")], [Output("knowledge_base", is_error=True)]),
    )

    [tool] = recorder.finish().tools
    assert (tool.name, tool.calls, tool.errors) == ("knowledge_base", 3, 1)


def test_a_malformed_metric_does_not_end_the_call(recorder):
    """Losing a number is acceptable; losing the conversation is not."""
    session = FakeSession()
    recorder.attach(session)
    session.fire("metrics_collected", MetricsEvent(None))
    session.fire("conversation_item_added", ItemEvent(None))
    session.fire("function_tools_executed", ToolsEvent(None, None))

    record = recorder.finish()
    assert record.outcome == OUTCOME_COMPLETED
    assert record.user_turns == 0


def test_an_error_event_marks_the_call(recorder):
    session = FakeSession()
    recorder.attach(session)

    @dataclass
    class ErrorEvent:
        error: str

    session.fire("error", ErrorEvent("tts provider unreachable"))
    record = recorder.finish()
    assert record.outcome == OUTCOME_ERROR
    assert "unreachable" in (record.error or "")


def test_the_config_is_snapshotted_not_referenced(recorder, config):
    """The saved config may be edited later; the record must not change with it."""
    record = recorder.finish()
    assert record.config["prompt"]["instructions"] == config.prompt.instructions
    assert record.config_id == config.id
    assert record.providers["llm"] == "google"


def test_finish_stamps_timing_and_reason(recorder):
    record = recorder.finish(shutdown_reason="user hung up")
    assert record.started_at.endswith("Z")
    assert record.ended_at and record.ended_at.endswith("Z")
    assert record.duration_seconds is not None and record.duration_seconds >= 0
    assert record.shutdown_reason == "user hung up"


# --- when the record gets written -----------------------------------------------


@dataclass
class CloseEvent:
    reason: str


def test_session_close_writes_the_record(tmp_path: Path, recorder):
    """The browser is polling from the moment it disconnects, so close is the
    trigger that matters. Job shutdown alone landed ~24s late in practice."""
    store = CallStore(tmp_path)
    writer = _RecordWriter(recorder, store)
    writer.on_session_close(CloseEvent("participant_disconnected"))
    assert store.load(CALL_ID).shutdown_reason == "participant_disconnected"


async def test_job_shutdown_does_not_write_twice(tmp_path: Path, recorder):
    store = CallStore(tmp_path)
    writer = _RecordWriter(recorder, store)
    writer.on_session_close(CloseEvent("participant_disconnected"))
    await writer.on_job_shutdown("parent process shutdown")

    # The close reason survives; the later shutdown was a no-op.
    assert store.load(CALL_ID).shutdown_reason == "participant_disconnected"


async def test_job_shutdown_is_the_fallback_when_close_never_fires(
    tmp_path: Path, recorder
):
    """A crashed or drained session may never emit close."""
    store = CallStore(tmp_path)
    writer = _RecordWriter(recorder, store)
    await writer.on_job_shutdown("worker drained")
    assert store.load(CALL_ID).shutdown_reason == "worker drained"


def test_a_failed_write_does_not_raise(tmp_path: Path, recorder):
    """A broken write must not turn a completed call into a crashed job."""

    class Broken(CallStore):
        def save(self, record):
            raise OSError("disk full")

    _RecordWriter(recorder, Broken(tmp_path)).on_session_close(CloseEvent("x"))


# --- store ----------------------------------------------------------------------


def test_save_then_load_round_trips(tmp_path: Path, recorder):
    store = CallStore(tmp_path)
    saved = recorder.finish()
    store.save(saved)
    assert store.load(CALL_ID).to_dict() == saved.to_dict()


def test_missing_record_raises(tmp_path: Path):
    with pytest.raises(CallNotFoundError):
        CallStore(tmp_path).load("nope")


def test_exists_reports_before_and_after(tmp_path: Path, recorder):
    store = CallStore(tmp_path)
    assert store.exists(CALL_ID) is False
    store.save(recorder.finish())
    assert store.exists(CALL_ID) is True


def test_list_is_newest_first_and_skips_unreadable(tmp_path: Path, config):
    store = CallStore(tmp_path)
    for call_id, started in [
        ("a", "2026-08-17T09:00:00Z"),
        ("b", "2026-08-17T11:00:00Z"),
    ]:
        rec = CallRecorder(call_id, config).finish()
        store.save(
            type(rec)(**{**rec.__dict__, "call_id": call_id, "started_at": started})
        )
    (tmp_path / "broken.json").write_text("{ not json")

    assert [r.call_id for r in store.list()] == ["b", "a"]


def test_a_call_id_cannot_escape_the_directory(tmp_path: Path, recorder):
    """Room names are safe, but a record id reaching the filesystem deserves care."""
    store = CallStore(tmp_path)
    assert store._path("../../etc/passwd").parent == tmp_path


def test_list_of_a_missing_directory_is_empty(tmp_path: Path):
    assert CallStore(tmp_path / "nothing").list() == []


def test_record_from_dict_tolerates_unknown_keys():
    """A record written by a newer version should still be listable."""
    rebuilt = record_from_dict({"call_id": "x", "started_at": "t", "future_field": 1})
    assert rebuilt.call_id == "x"
    assert rebuilt.totals.tokens.total_tokens == 0


# --- redaction seam -------------------------------------------------------------


def test_redaction_is_a_no_op_by_default():
    assert redact("call me on 98765 43210") == "call me on 98765 43210"


def test_redaction_strategy_can_be_swapped():
    try:
        set_redactor(lambda text: "[redacted]")
        assert redact("anything") == "[redacted]"
    finally:
        set_redactor(identity)


# --- the read API ---------------------------------------------------------------


@pytest.fixture
def client(tmp_path: Path, recorder):
    CallStore(tmp_path / "calls").save(recorder.finish())
    with TestClient(
        create_app(config_dir=tmp_path / "configs", call_log_dir=tmp_path / "calls")
    ) as client:
        yield client


def test_list_returns_summaries_without_the_config(client):
    [summary] = client.get("/api/calls").json()
    assert summary["call_id"] == CALL_ID
    assert "config" not in summary
    assert "total_tokens" in summary


def test_get_returns_the_full_record_including_the_config(client):
    body = client.get(f"/api/calls/{CALL_ID}").json()
    assert body["config"]["llm"]["provider"] == "google"
    assert body["providers"]["tts"] == "elevenlabs"


def test_unknown_call_is_404(client):
    """The browser polls this after hang-up, so 404 has to mean 'not yet'."""
    assert client.get("/api/calls/does-not-exist").status_code == 404


def test_logs_page_and_script_are_served(client):
    assert "Call log" in client.get("/logs.html").text
    assert client.get("/logs.js").status_code == 200


def test_there_is_no_way_to_write_a_call_record(client):
    """A log the application can rewrite is not much of a record."""
    assert client.post("/api/calls", json={}).status_code in (404, 405)
