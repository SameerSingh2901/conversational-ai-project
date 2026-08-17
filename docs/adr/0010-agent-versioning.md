# 0010 — Agent version history: append-only versions

**Status:** Proposed

## Context

Customers need to edit agents without losing the ability to answer "what did this
call actually run". Today every config save mints a new id and never overwrites —
the right instinct — but **there is no identity linking two saves as the same
agent**. Each save produces a separate agent.

## Decision

```
agents           id · account_id · name · published_version_id · archived_at
agent_versions   id · agent_id · version_number · definition (JSONB)
                 message · created_by · created_at · parent_version_id
calls            … · agent_version_id      -- not agent_id alone
```

- **Snapshots, not deltas.** A definition is a couple of KB. Diffs are computed on
  read between two snapshots.
- **`agent_versions` is append-only.** No update, no delete.
- **Publishing moves `published_version_id`; editing writes a row.** Drafts prevent a
  half-finished prompt answering a live call.
- **Rollback publishes an old version**, leaving newer ones intact. Git's revert, not
  reset.
- **Calls store `agent_version_id`**, so a call from last month still shows the exact
  prompt, voice and model that produced it.

## Consequences

- Storage is trivial and the model is easy to reason about.
- Pointer moves need auditing (who published what, when) — hence `audit_log`.
- Branching is possible later via `parent_version_id` but is not built.
