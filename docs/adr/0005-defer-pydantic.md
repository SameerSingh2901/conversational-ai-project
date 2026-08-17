# 0005 — Hand-rolled validation; pydantic deferred

**Status:** Accepted

## Context

Config documents need validation. FastAPI ships with pydantic, which would provide
validation, JSON Schema generation for the console form, and request parsing from
one definition.

## Decision

Hand-rolled dataclasses and a `parse_config()` function, deliberately, to keep the
validation logic explicit and learnable. Request bodies are read as raw JSON and
handed to the same validator rather than declared as pydantic models.

## Consequences

- One validator, not two that can drift.
- ~250 lines written that pydantic would have provided.
- **The swap is confined to `schema.py`** because the error contract deliberately
  copies pydantic's: a list of errors, each with a `loc` tuple and a `msg`. The
  store, API, console and pipeline consume that shape and would not change.
- `describe_stages()` is the hand-rolled stand-in for `model_json_schema()`. Its
  body would change; its output shape would not.
- Every new validation rule (ranges, URL formats, cross-field checks) is code we
  write and test ourselves. That bill grows slowly and then all at once.
