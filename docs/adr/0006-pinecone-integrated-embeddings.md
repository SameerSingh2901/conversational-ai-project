# 0006 — Pinecone with server-side embeddings

**Status:** Accepted

## Context

The retrieval tool needs a vector store. The knowledge base is currently ~3,400
characters, which would fit in a system prompt with room to spare.

## Options

1. No retrieval — put the documents in the prompt.
2. pgvector on the Postgres we will need anyway.
3. A separate embedding provider plus any vector store.
4. **Pinecone with integrated (server-side) embedding.**

## Decision

Pinecone, embedding server-side: text goes in, text comes out.

Option 1 is genuinely better for the corpus we have today. Retrieval was built for
the shape of the problem — hundreds of documents — not its current size, where
prompt-stuffing wins on latency and simplicity.

## Consequences

- One credential instead of two, and no embedding provider in the latency path.
- The ingest path and the query path **cannot** disagree about the embedding model
  or its dimensions. That mismatch does not error; it silently returns bad results.
- Costs: the embedding model is vendor-chosen and changing it means recreating the
  index; ~1.2 s round trip from India to `us-east-1`, which is expensive in a turn.
- The namespace is the natural tenant boundary — one per account. Today it is a
  single value from an environment variable, which is a multi-tenancy blocker
  (ADR-0009).
