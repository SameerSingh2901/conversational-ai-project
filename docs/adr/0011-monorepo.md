# 0011 — Monorepo with uv workspaces

**Status:** Proposed

## Context

The platform needs at least four deployable things: the API, the LiveKit worker, a
queue consumer, and a web console. They share the agent definition schema, the
provider catalogue and the pipeline.

## Decision

One repository:

```
apps/{api,worker,ingest,console}
packages/{core,db}
infra/
docs/adr/
```

`packages/core` is today's `src/voice_agent`, almost unchanged, and stays free of
HTTP, database and AWS concerns.

## Consequences

- A change to the agent definition schema touches the API, the worker and the console
  at once, and lands in one reviewable commit.
- Loses independent deploy cadence per service, which is not needed at this size.
- The API and worker both depend on `core` without depending on each other, which
  preserves the dependency rule that already governs the codebase.
- Step 1 of the migration is a pure file move: tests must pass unchanged.
