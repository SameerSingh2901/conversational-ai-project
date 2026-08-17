# CLAUDE.md

Read this first. It is the index to everything else.

---

## The project

A **config-driven voice agent platform**. An agent is entirely described by a JSON
document — STT / LLM / TTS / VAD providers, the system prompt, and the tools it may
call. Change any of it in a browser, press Run, and talk to the result. Nothing
about a use case lives in code.

It currently runs as a single-user tool on one laptop. **The goal is a
multi-tenant SaaS**: companies sign up, buy credits, build agents, connect a CRM,
take real phone calls, and review every call afterwards with its transcript,
recording and latency trace.

## Start here

| File | What it answers |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | How the code works **today** — file by file, both data-flow traces, invariants, and the bugs that shaped it |
| [`PROGRESS.md`](PROGRESS.md) | What is built, what is next, and every problem hit along the way |
| [`docs/PLATFORM-PLAN.md`](docs/PLATFORM-PLAN.md) | The product: capability map, AWS design, storage maths, unit economics, compliance, phases to revenue |
| [`docs/ENGINEERING-PLAN.md`](docs/ENGINEERING-PLAN.md) | How to build it: repo and workflow, agent version history, the stack in arrival order, security model, migration, 14-week sequence |
| [`docs/adr/`](docs/adr/) | **Why** each decision was made, and what it cost |
| [`README.md`](README.md) | Setup and quick start |

## Where things stand

**Built and working** (single tenant, local): the provider catalogue, config
validation and storage, the FastAPI control plane, a browser console, the LiveKit
worker with per-session pipeline construction, a Pinecone-backed retrieval tool,
and call overview logging with a per-call log page.

**Not built**: per-turn latency, stored transcripts, telephony, accounts, billing,
CRM integrations, anything on AWS.

**The next unit of work** is week 1 of `docs/ENGINEERING-PLAN.md` §10 — the
monorepo move, CI on pull requests, and the first ADRs. Weeks 1–6 need no AWS
account, no payment gateway and no customer.

## Commands

```bash
make ui                    # config console + API on :8000
make worker                # LiveKit worker (needs `brew install livekit-cli`)
make agent CONFIG=<id>     # talk to a saved config in the terminal
make agent-text CONFIG=<id># same, typed, no mic or TTS spend
make ingest                # load knowledge/ into Pinecone
make configs               # list saved config ids
make check                 # lock, format, lint, mypy --strict
make test                  # pytest
```

## Non-negotiables

These are load-bearing. Breaking one is a regression even if the tests pass.

1. **Dependencies point one way.** `config/` imports nothing else in the project.
   Nothing in it may ever import from `api/`.
2. **`parse_config()` is the only path** from a raw dict to an `AgentConfig`. No
   code downstream inspects raw JSON.
3. **The catalogue is the single source of truth.** Provider facts live in
   `config/providers.py` and are read by the validator, the console, the credential
   gate and the pipeline builders. The console must never hardcode a provider name.
4. **Pipelines are built per session**, inside `session()`, never at import. No
   module-level provider globals. This is what lets one worker serve every config.
5. **Secrets never enter a config document.** Configs travel over HTTP to browsers
   and onto LiveKit rooms.
6. **LiveKit plugins are imported at module level.** They register on import and
   refuse to do it off the main thread; builders run in the job runner thread.
7. **Call records are written on session close**, not job shutdown — the job
   lingers ~24s uploading its session report.

## Known limits

- `ConfigStore.list()` and `CallStore.list()` read every record. Fine locally,
  wrong past a few thousand. Both are `save/load/list` interfaces so the swap to
  Postgres is one file each.
- `tools/knowledge_base.py` holds a module-level `_kb` singleton scoped by an env
  var. **This is a cross-tenant leak the moment there is a second account** — see
  ADR-0009.
- Nothing in `src/` references an account, tenant or user.
- `metrics_collected` is deprecated in favour of `session_usage_updated` and
  `ChatMessage.metrics`. Ours still records correctly; migrate with the per-turn
  work so the event shapes can be checked against a live call.

## Published artifacts

Same content as the docs, rendered. Republish by file path to keep the URL.

- Architecture walkthrough — `claude.ai/code/artifact/35ad2cb4-12bf-4d1c-b2a6-4233af73b886`
- Platform plan — `claude.ai/code/artifact/397c5a1b-1d9b-4816-8ac9-eff04df6d926`
- Engineering plan — `claude.ai/code/artifact/f11c4455-b0cc-4108-aac0-4c435a6086d1`

---

# Working guidelines

From [multica-ai/andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills).
Also installed as skills under `.claude/skills/`, alongside 24 workflow skills from
[addyosmani/agent-skills](https://github.com/addyosmani/agent-skills).

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.
