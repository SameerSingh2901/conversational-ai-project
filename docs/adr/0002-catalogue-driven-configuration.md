# 0002 — One provider catalogue, four consumers

**Status:** Accepted

## Context

The original code selected providers with `if/elif` chains reading module-level
constants. Every new provider meant editing shared functions, and the UI, the
validator and the pipeline each held their own idea of what a provider was.

## Decision

`config/providers.py` holds one table. Each `ProviderSpec` declares its fields,
their types, defaults, allowed values, and the environment variable that gates it.

Four consumers read that same table:

1. `config/schema.py` — validation
2. `GET /api/providers` → the console — form generation
3. `config/env.py` — credential gating
4. `pipeline.py` — builder lookup

## Consequences

- Adding a provider is one table entry plus one registered builder. No UI change.
- The console must never hardcode a provider name. This is the property to protect.
- One coupling remains: names in the catalogue must match names in the registry.
  Two tests guard it (`test_every_catalogue_provider_has_a_builder` and its reverse).
- The same pattern extends to tools, integrations and channels — see
  `docs/ENGINEERING-PLAN.md` §1.
