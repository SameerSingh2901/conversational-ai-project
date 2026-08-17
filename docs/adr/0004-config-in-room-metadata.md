# 0004 — The config travels as LiveKit room metadata

**Status:** Accepted, with a known limit

## Context

The API and the worker are separate processes that must agree on which agent a call
runs. The worker learns about a call only when LiveKit hands it a job.

## Options

1. Pass a config **id**; the worker fetches the definition itself.
2. **Pass the whole definition** on the room.

## Decision

The API stamps the full config document onto the room at creation
(`POST /api/sessions`). The worker reads it from `ctx.job.room.metadata`.

## Consequences

- The call is a **snapshot**: editing a config cannot change a conversation already
  in flight.
- The worker needs no access to the config store, so it stays stateless and shares
  no filesystem with the API.
- Costs: metadata size (a config is 1–2 KB, well inside limits), and config genuinely
  cannot be changed mid-call.
- **Limit:** this breaks once agents hold customer credentials for integrations —
  that would write a customer's CRM token into a third party's room record. The
  planned fix keeps the snapshot but replaces credential fields with references plus
  a short-lived scoped token. See `docs/ENGINEERING-PLAN.md` §3.
- Read metadata from `ctx.job.room`, **not** `ctx.room` — the room object has not
  connected when the entrypoint runs, so its metadata is empty.
