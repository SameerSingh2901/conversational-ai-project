# 0008 — File-based stores behind a swappable interface

**Status:** Accepted, with a known ceiling

## Context

Configs and call records need persistence. A database is the eventual answer; it was
not the fastest way to get a working product.

## Decision

`ConfigStore` and `CallStore` write JSON files under `configs/` and `call_logs/`,
exposing `save / load / list`. Callers only ever use those methods.

## Consequences

- Zero infrastructure. Configs are greppable and committable; call records are
  gitignored because they will hold caller speech.
- **`list()` reads and parses every record ever written.** At a thousand records the
  page is slow; at a million it never returns. Most filesystems also degrade past
  ~10k files in a directory.
- No index, so filtering by owner or date means reading everything. No pagination.
  Worker and API must share a disk.
- The swap to Postgres replaces three method bodies and touches no caller. That was
  the point of the interface. See `docs/PLATFORM-PLAN.md` §6 for the storage maths.
- Every save mints a new timestamped id and never overwrites, which gives config
  history for free — and is the instinct ADR-0010 formalises.
