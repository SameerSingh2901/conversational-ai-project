# 0009 — Multi-tenancy: account_id at the repository layer

**Status:** Proposed

## Context

Nothing in `src/` references an account, tenant or user. Every store is scoped by a
process-level environment variable. Three specific things break with a second
customer:

1. **`tools/knowledge_base.py` holds `_kb` as a module-level singleton**, built once
   per process from an env-var Pinecone namespace. With many accounts the first
   namespace is cached and served to every later call in that process — customer A's
   documents answering customer B's caller.
2. Storage paths come from `VOICE_AGENT_CONFIG_DIR`, `VOICE_AGENT_CALL_LOG_DIR` and
   `PINECONE_NAMESPACE`, all process-wide.
3. `list()` cannot filter by owner because there is no owner.

## Decision

- `account_id` on every table, passed as the **first argument to every repository
  method**, so a query cannot be written without one. Filtering happens in the data
  access layer, never in a route handler.
- Postgres row-level security as a backstop: a forgotten filter returns nothing
  rather than everything.
- The knowledge base is constructed **per call** from the agent definition and reached
  through `RunContext.userdata`, not a module global. Pinecone namespace = account id.
- A test asserting account B cannot read account A's calls, agents or documents,
  written before the second account exists.

## Consequences

- The singleton fix uses the same `RunContext.userdata` plumbing as per-turn tool
  tracing, so the two changes belong in one piece of work.
- Repository signatures change everywhere; callers are mechanical to update.
- This must land before any external user, not after.
