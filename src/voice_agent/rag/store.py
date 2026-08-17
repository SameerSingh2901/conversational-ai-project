"""Pinecone-backed vector store.

Uses Pinecone's **integrated embedding**: you upsert text and search with text,
and Pinecone runs the embedding model server-side. That keeps this to a single
credential — no second provider to key, no embedding dimensions to keep in sync
between the ingest path and the query path, which is a classic way for a RAG
system to break silently.

The client is created lazily so importing this module never requires a key.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from voice_agent.rag.documents import Chunk

if TYPE_CHECKING:
    from pinecone import Pinecone

DEFAULT_INDEX = "voice-agent-knowledge"
DEFAULT_NAMESPACE = "knowledge"

# Pinecone-hosted embedding model. Changing this means re-creating the index.
EMBED_MODEL = "llama-text-embed-v2"
CLOUD = "aws"
REGION = "us-east-1"

# The record field Pinecone embeds, per the index's field_map.
TEXT_FIELD = "chunk_text"

_UPSERT_BATCH = 90


class KnowledgeBaseError(RuntimeError):
    """Pinecone is unreachable, unconfigured, or the index does not exist."""


@dataclass(frozen=True)
class Passage:
    """One retrieved chunk."""

    text: str
    section: str
    source: str
    score: float


class KnowledgeBase:
    def __init__(
        self, index_name: str | None = None, namespace: str | None = None
    ) -> None:
        self.index_name = index_name or os.environ.get("PINECONE_INDEX", DEFAULT_INDEX)
        self.namespace = namespace or os.environ.get(
            "PINECONE_NAMESPACE", DEFAULT_NAMESPACE
        )
        self._client: Pinecone | None = None

    # --- plumbing ---------------------------------------------------------

    def _pinecone(self) -> Pinecone:
        if self._client is None:
            key = os.environ.get("PINECONE_API_KEY", "").strip()
            if not key:
                raise KnowledgeBaseError("PINECONE_API_KEY is not set")
            from pinecone import Pinecone as _Pinecone

            self._client = _Pinecone(api_key=key)
        return self._client

    def _index(self) -> Any:
        return self._pinecone().Index(self.index_name)

    def ensure_index(self) -> bool:
        """Create the index if it is missing. Returns True when it created one."""
        pc = self._pinecone()
        if pc.has_index(self.index_name):
            return False
        pc.create_index_for_model(
            name=self.index_name,
            cloud=CLOUD,
            region=REGION,
            embed={"model": EMBED_MODEL, "field_map": {"text": TEXT_FIELD}},
        )
        return True

    # --- write ------------------------------------------------------------

    def upsert(self, chunks: list[Chunk]) -> int:
        """Upsert chunks by id, so re-ingesting the same document replaces it."""
        if not chunks:
            return 0
        index = self._index()
        records = [
            {
                "_id": chunk.id,
                TEXT_FIELD: chunk.text,
                "section": chunk.section,
                "source": chunk.source,
            }
            for chunk in chunks
        ]
        for start in range(0, len(records), _UPSERT_BATCH):
            index.upsert_records(
                namespace=self.namespace,
                records=records[start : start + _UPSERT_BATCH],
            )
        return len(records)

    def stats(self) -> dict[str, Any]:
        raw = self._index().describe_index_stats()
        return dict(raw) if not isinstance(raw, dict) else raw

    # --- read -------------------------------------------------------------

    def search(self, question: str, top_k: int = 3) -> list[Passage]:
        """Nearest chunks to a question. Blocking — call it off the event loop."""
        if not question.strip():
            return []
        try:
            response = self._index().search_records(
                namespace=self.namespace,
                query={"inputs": {"text": question}, "top_k": top_k},
                fields=[TEXT_FIELD, "section", "source"],
            )
        except Exception as exc:  # surfaced to callers as one error type
            raise KnowledgeBaseError(f"Pinecone search failed: {exc}") from exc

        return [
            Passage(
                text=str(fields.get(TEXT_FIELD, "")),
                section=str(fields.get("section", "")),
                source=str(fields.get("source", "")),
                score=_score(hit),
            )
            for hit in _hits(response)
            if (fields := dict(hit.get("fields", {})))
        ]


def _hits(response: Any) -> list[dict[str, Any]]:
    """Pull hits out of the response whether it is a model or a plain dict."""
    payload = response if isinstance(response, dict) else response.to_dict()
    result = payload.get("result") or {}
    return [dict(hit) for hit in result.get("hits", [])]


def _score(hit: dict[str, Any]) -> float:
    """Read the similarity score.

    This SDK returns `score_`; other versions and the REST docs use `_score`.
    Accept both — reading the wrong one yields a silent 0.0 for every hit, which
    a relevance threshold then rejects wholesale.
    """
    for key in ("score_", "_score", "score"):
        if key in hit:
            return float(hit[key])
    return 0.0
