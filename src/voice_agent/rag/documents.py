"""Reading source documents and splitting them into retrievable chunks.

Deliberately dependency-light: PDFs via pypdf, plain text and markdown read
directly. No document-loader framework — for a knowledge base of this size the
framework would be larger than the problem.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

SUPPORTED_SUFFIXES = (".pdf", ".md", ".txt")

# A heading is a short line that does not read like a sentence. Tuned against
# pypdf output, where body text arrives as long wrapped lines and a heading sits
# alone on a short one.
_MAX_HEADING_LEN = 60
_SENTENCE_ENDINGS = (".", ",", ";", ":")

# Used only when heading detection finds nothing to work with.
_FALLBACK_CHUNK_CHARS = 700
_FALLBACK_OVERLAP_CHARS = 120


@dataclass(frozen=True)
class Chunk:
    """One retrievable passage, with enough provenance to cite it."""

    id: str
    text: str
    source: str
    section: str


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "chunk"


def read_document(path: Path) -> str:
    """Extract plain text from one file."""
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    return path.read_text(encoding="utf-8")


def _looks_like_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > _MAX_HEADING_LEN:
        return False
    if stripped.endswith(_SENTENCE_ENDINGS):
        return False
    # Markdown headings are unambiguous.
    if stripped.startswith("#"):
        return True
    return stripped[0].isupper() or stripped[0].isdigit()


def _split_by_size(text: str, source: str) -> list[Chunk]:
    """Fallback for documents with no detectable structure."""
    words = text.split()
    chunks: list[Chunk] = []
    start = 0
    index = 0
    while start < len(words):
        piece: list[str] = []
        length = 0
        cursor = start
        while cursor < len(words) and length < _FALLBACK_CHUNK_CHARS:
            piece.append(words[cursor])
            length += len(words[cursor]) + 1
            cursor += 1
        body = " ".join(piece).strip()
        if body:
            chunks.append(
                Chunk(
                    id=f"{_slug(source)}--{index}",
                    text=body,
                    source=source,
                    section=f"part {index + 1}",
                )
            )
            index += 1
        if cursor >= len(words):
            break
        overlap_words = max(1, _FALLBACK_OVERLAP_CHARS // 6)
        start = cursor - overlap_words
    return chunks


def chunk_text(text: str, source: str) -> list[Chunk]:
    """Split a document into one chunk per section, falling back to size."""
    sections: list[tuple[str, list[str]]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if _looks_like_heading(line):
            sections.append((line.lstrip("# ").strip(), []))
        elif sections:
            sections[-1][1].append(line)
        else:
            sections.append(("Introduction", [line]))

    # A document where nearly every line looked like a heading, or none did,
    # has not really been understood — chunk it by size instead.
    usable = [(title, body) for title, body in sections if body]
    if len(usable) < 2:
        return _split_by_size(text, source)

    chunks: list[Chunk] = []
    for index, (title, body) in enumerate(usable):
        # Keep the heading inside the chunk: it is a strong retrieval signal and
        # it lets the agent name the section it is quoting.
        passage = f"{title}\n{' '.join(body)}".strip()
        chunks.append(
            Chunk(
                id=f"{_slug(source)}--{index}--{_slug(title)[:40]}",
                text=passage,
                source=source,
                section=title,
            )
        )
    return chunks


def load_chunks(root: Path | str) -> list[Chunk]:
    """Every chunk from every supported document under `root`."""
    root = Path(root)
    if not root.is_dir():
        raise FileNotFoundError(f"no such directory: {root}")

    chunks: list[Chunk] = []
    for path in sorted(root.rglob("*")):
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        text = read_document(path)
        if not text.strip():
            continue
        chunks.extend(chunk_text(text, source=path.name))
    return chunks
