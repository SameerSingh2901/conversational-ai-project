"""Retrieval tests. Nothing here touches the network."""

from pathlib import Path
from typing import Any

import pytest

from voice_agent.rag import documents
from voice_agent.rag.documents import Chunk, chunk_text, load_chunks
from voice_agent.rag.store import (
    KnowledgeBase,
    KnowledgeBaseError,
    Passage,
    _hits,
    _score,
)
from voice_agent.tools import TOOLS, resolve_tools
from voice_agent.tools import knowledge_base as kb_tool

SAMPLE_PDF = Path("knowledge/spinny-policies.pdf")

# The tool never touches its RunContext; typing it away keeps mypy honest
# about the real signature while letting the tests call it directly.
NO_CONTEXT: Any = None

STRUCTURED = """Return Policy
You may return the car within 5 days of delivery. The full amount is refunded.
Warranty
Assured cars include a one year warranty covering the engine and transmission.
Support Hours
Support is available every day from 9 AM to 9 PM.
"""


# --- chunking --------------------------------------------------------------------


def test_headings_become_separate_chunks():
    chunks = chunk_text(STRUCTURED, source="policies.pdf")
    assert [c.section for c in chunks] == ["Return Policy", "Warranty", "Support Hours"]


def test_chunk_keeps_its_heading_in_the_text():
    """The heading is a strong retrieval signal and lets the agent cite a section."""
    chunks = chunk_text(STRUCTURED, source="policies.pdf")
    assert chunks[0].text.startswith("Return Policy")
    assert "5 days" in chunks[0].text


def test_chunk_ids_are_stable_across_runs():
    """Ids drive upsert, so re-ingesting must replace rather than duplicate."""
    first = chunk_text(STRUCTURED, source="policies.pdf")
    second = chunk_text(STRUCTURED, source="policies.pdf")
    assert [c.id for c in first] == [c.id for c in second]
    assert len({c.id for c in first}) == len(first)


def test_body_lines_ending_in_a_full_stop_are_not_headings():
    chunks = chunk_text(STRUCTURED, source="p.pdf")
    assert all("You may return" not in c.section for c in chunks)


def test_unstructured_text_falls_back_to_size_chunks():
    prose = "This document has no headings at all. " * 80
    chunks = chunk_text(prose, source="blob.txt")
    assert len(chunks) > 1
    assert all(c.section.startswith("part ") for c in chunks)


def test_single_section_document_falls_back_too():
    chunks = chunk_text("Just One Heading\nAnd a single line of body text.", "x.md")
    assert all(c.section.startswith("part ") for c in chunks)


def test_markdown_headings_are_recognised():
    md = "# Refunds\nRefunds take 7 days.\n# Delivery\nDelivery takes 3 days.\n"
    assert [c.section for c in chunk_text(md, "faq.md")] == ["Refunds", "Delivery"]


# --- the real sample document ----------------------------------------------------


def test_sample_pdf_chunks_into_sections():
    chunks = load_chunks("knowledge")
    sections = {c.section for c in chunks}
    assert "5-Day Money-Back Guarantee" in sections
    assert "One-Year Warranty" in sections
    assert all(c.source == "spinny-policies.pdf" for c in chunks)


def test_sample_pdf_carries_its_demo_disclaimer():
    """The sample data must not be mistaken for a real policy document."""
    text = documents.read_document(SAMPLE_PDF).upper()
    assert "SAMPLE DATA" in text
    assert "NOT AN OFFICIAL" in text


def test_unsupported_files_are_skipped(tmp_path: Path):
    (tmp_path / "notes.docx").write_text("ignored")
    (tmp_path / "faq.md").write_text("# A\nbody one.\n# B\nbody two.\n")
    assert {c.source for c in load_chunks(tmp_path)} == {"faq.md"}


def test_missing_directory_is_an_error():
    with pytest.raises(FileNotFoundError):
        load_chunks("no/such/place")


# --- response parsing ------------------------------------------------------------


def test_score_reads_this_sdks_key():
    assert _score({"score_": 0.42}) == pytest.approx(0.42)


def test_score_reads_the_documented_key_too():
    """Reading the wrong key yields 0.0 for every hit, which a threshold rejects."""
    assert _score({"_score": 0.42}) == pytest.approx(0.42)
    assert _score({"score": 0.42}) == pytest.approx(0.42)
    assert _score({}) == 0.0


def test_hits_parses_a_plain_dict_response():
    payload = {"result": {"hits": [{"id_": "a", "score_": 0.9, "fields": {}}]}}
    assert _hits(payload)[0]["id_"] == "a"


def test_hits_of_an_empty_response():
    assert _hits({}) == []


# --- the store -------------------------------------------------------------------


def test_missing_api_key_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("PINECONE_API_KEY", raising=False)
    with pytest.raises(KnowledgeBaseError, match="PINECONE_API_KEY"):
        KnowledgeBase().ensure_index()


def test_index_and_namespace_come_from_env(monkeypatch):
    monkeypatch.setenv("PINECONE_INDEX", "other-index")
    monkeypatch.setenv("PINECONE_NAMESPACE", "other-ns")
    kb = KnowledgeBase()
    assert (kb.index_name, kb.namespace) == ("other-index", "other-ns")


def test_upsert_of_nothing_does_not_call_pinecone():
    assert KnowledgeBase().upsert([]) == 0


# --- the tool --------------------------------------------------------------------


class FakeKB:
    def __init__(self, passages=(), error=None):
        self.passages = list(passages)
        self.error = error
        self.asked: list[str] = []

    def search(self, question, top_k=3):
        self.asked.append(question)
        if self.error:
            raise self.error
        return self.passages[:top_k]


@pytest.fixture
def fake_kb(monkeypatch):
    def install(passages=(), error=None):
        fake = FakeKB(passages, error)
        monkeypatch.setattr(kb_tool, "_kb", fake)
        return fake

    return install


def passage(section, score, text="some policy text"):
    return Passage(
        text=f"{section}\n{text}", section=section, source="p.pdf", score=score
    )


def test_tool_is_registered_and_resolvable():
    assert "knowledge_base" in TOOLS
    assert resolve_tools(["knowledge_base"])[0].info.name == "knowledge_base"


def test_tool_description_tells_the_model_when_to_call_it():
    description = (resolve_tools(["knowledge_base"])[0].info.description or "").lower()
    assert "polic" in description
    assert "warrant" in description or "refund" in description


async def test_relevant_passages_are_returned_with_their_section(fake_kb):
    fake_kb([passage("One-Year Warranty", 0.51)])
    out = await kb_tool.knowledge_base(NO_CONTEXT, question="how long is the warranty")
    assert "[One-Year Warranty]" in out
    assert "some policy text" in out


async def test_the_question_reaches_the_store_verbatim(fake_kb):
    fake = fake_kb([passage("Warranty", 0.5)])
    await kb_tool.knowledge_base(NO_CONTEXT, question="what about the warranty?")
    assert fake.asked == ["what about the warranty?"]


async def test_weak_matches_are_dropped(fake_kb):
    """Retrieval always returns something; a low score means it is noise."""
    fake_kb([passage("Fixed Price", 0.03)])
    out = await kb_tool.knowledge_base(NO_CONTEXT, question="who won the world cup")
    assert "Fixed Price" not in out
    assert "do not have" in out


async def test_a_strong_hit_survives_alongside_weak_ones(fake_kb):
    fake_kb([passage("Warranty", 0.50), passage("Delivery", 0.02)])
    out = await kb_tool.knowledge_base(NO_CONTEXT, question="warranty?")
    assert "[Warranty]" in out
    assert "[Delivery]" not in out


async def test_store_failure_does_not_break_the_call(fake_kb):
    """A raised exception mid-conversation would kill the session."""
    fake_kb(error=KnowledgeBaseError("pinecone unreachable"))
    out = await kb_tool.knowledge_base(NO_CONTEXT, question="anything")
    assert "unavailable" in out.lower()


async def test_empty_result_tells_the_model_not_to_guess(fake_kb):
    fake_kb([])
    out = await kb_tool.knowledge_base(NO_CONTEXT, question="anything")
    assert "guess" in out.lower()


# --- the config that uses it -----------------------------------------------------


def test_a_config_can_enable_the_tool_by_name():
    from voice_agent.config import ConfigStore

    configs = [c for c in ConfigStore("configs").list() if "knowledge_base" in c.tools]
    assert configs, "expected a saved config wired to the knowledge base"
    assert resolve_tools(configs[0].tools)


def test_chunk_is_immutable():
    chunk = Chunk(id="a", text="t", source="s", section="sec")
    with pytest.raises(AttributeError):
        chunk.text = "changed"  # type: ignore[misc]
