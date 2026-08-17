# 0007 — Write the call record on session close

**Status:** Accepted (supersedes an earlier choice of job shutdown)

## Context

Call records must be written when a call ends, and the browser polls for the record
immediately after hanging up.

## First attempt

`ctx.add_shutdown_callback`, which guarantees the write runs.

**It ran ~24 seconds late.** LiveKit uploads its session report to the cloud before
shutting the job down. In a measured call the session closed at 11:47:21 and the job
did not shut down until 11:47:45 — long after the browser stopped polling and showed
"No log was written for this call".

## Decision

`_RecordWriter` writes on `session.on("close")`, which fires the moment the caller
disconnects, and keeps the shutdown callback as a fallback for sessions that never
close cleanly (a crash, a drained worker). It writes exactly once; whichever fires
first wins.

## Consequences

- Guaranteed and prompt are different properties. Both hooks are needed.
- Writing from the synchronous close handler is safe: the call is over, there is no
  audio left to stall, and the file is a couple of kilobytes.
- `GET /api/calls/{id}` returning 404 means "not yet", which is what lets the browser
  poll.
