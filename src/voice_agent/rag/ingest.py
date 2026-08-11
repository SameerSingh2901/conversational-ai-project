"""Load the knowledge/ folder into Pinecone.

    make ingest

Safe to re-run: chunk ids are derived from the document name and section, so a
second run replaces the same records rather than duplicating them.
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

from voice_agent.rag.documents import load_chunks
from voice_agent.rag.store import KnowledgeBase, KnowledgeBaseError

DEFAULT_SOURCE_DIR = Path("knowledge")


def main(source: Path | str = DEFAULT_SOURCE_DIR) -> int:
    load_dotenv()

    try:
        chunks = load_chunks(source)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if not chunks:
        print(f"nothing to ingest — no .pdf, .md or .txt files under {source}/")
        return 1

    by_source: dict[str, int] = {}
    for chunk in chunks:
        by_source[chunk.source] = by_source.get(chunk.source, 0) + 1
    for name, count in sorted(by_source.items()):
        print(f"  {name}: {count} chunks")

    kb = KnowledgeBase()
    try:
        if kb.ensure_index():
            print(f"created index {kb.index_name!r} — waiting for it to be ready")
            _wait_until_ready(kb)
        written = kb.upsert(chunks)
    except KnowledgeBaseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"upserted {written} chunks into {kb.index_name}/{kb.namespace}")
    return 0


def _wait_until_ready(kb: KnowledgeBase, attempts: int = 30) -> None:
    """A freshly created serverless index is not immediately writable."""
    import time

    for _ in range(attempts):
        try:
            kb.stats()
            return
        except Exception:  # noqa: BLE001 - index still provisioning
            time.sleep(2)
    raise KnowledgeBaseError(f"index {kb.index_name!r} did not become ready")


if __name__ == "__main__":
    raise SystemExit(main())
