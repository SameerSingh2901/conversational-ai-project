# Progress

Working document. Where this project is, where it's going, and the ordered steps
to get there. Update the checkboxes as steps land.

---

## What we are building

A **config-driven voice agent backend**. Not a real-estate agent — a generic
runtime where an agent is fully described by a JSON config (STT / LLM / TTS / VAD
providers plus a prompt and a tool list), and a small web UI to author those
configs, run them, talk to the agent, and inspect what happened.

The real-estate sales agent was a demo of what the runtime can do. It becomes one
saved config among many, not something baked into the code.

## Definition of done

1. Start the whole application with one or two commands and land on a page where
   I can **create a new config or load a previous one**.
2. In a new config I can **select STT / TTS / LLM providers and write the prompt**.
   Hitting Save persists it in the backend under a chosen **name + date + time**.
3. After saving, clicking **Run** sends that config to the backend, the voice
   pipeline starts, and I can **talk to the agent on the page itself and see live
   transcriptions**.
4. **Call details, transcriptions, the config used, and latency** are logged and
   saved, so I can go back and see what was happening during a call — latency
   especially.

## Prerequisites

| Tool | Install | Needed for |
|---|---|---|
| `uv` | already set up | everything |
| **LiveKit CLI (`lk`)** | `brew install livekit-cli` | `make agent` and `make worker` — LiveKit deprecated the agent's own `console` and `dev` subcommands in favour of `lk agent console` / `lk agent dev` |
| Ollama | `brew install ollama` + `ollama serve` | only configs whose LLM provider is `ollama` |
| Pinecone account | free tier at pinecone.io | only configs whose `tools` include `knowledge_base` |

Credentials go in `.env`, never in a config file: `LIVEKIT_URL`,
`LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `DEEPGRAM_API_KEY`, `GOOGLE_API_KEY`,
`ELEVEN_API_KEY`, `PINECONE_API_KEY`. See `.env.example`.

**A key being *set* is not the same as a key being *valid*.** `missing_credentials()`
only checks presence — an expired or revoked key still shows as available and then
fails mid-call as a 401. Quick checks:

```bash
set -a; . ./.env; set +a
curl -s -o /dev/null -w "deepgram   %{http_code}\n" -H "Authorization: Token $DEEPGRAM_API_KEY" https://api.deepgram.com/v1/projects
curl -s -o /dev/null -w "elevenlabs %{http_code}\n" -H "xi-api-key: $ELEVEN_API_KEY" https://api.elevenlabs.io/v1/user
curl -s -o /dev/null -w "google     %{http_code}\n" "https://generativelanguage.googleapis.com/v1beta/models?key=$GOOGLE_API_KEY"
```

200 means good, 401 means regenerate the key.

## Locked decisions

| Decision | Choice | Why |
|---|---|---|
| Config format | JSON | Machine-authored by the UI, diffable, no YAML ambiguity |
| Validation | **Stdlib dataclasses for now; pydantic later** | Deliberately deferred so the project stays learnable. The error shape (`FieldError.loc` + a list of them) copies pydantic's, so the swap is confined to `schema.py` — see "On pydantic" below |
| Prompt location | Inline in the config | The UI edits a textarea; that text *is* config. Kills `PROMPT_FILE` and the cwd-dependent path bug |
| Secrets | Env only, never in config JSON | Configs travel over HTTP to the browser; API keys must not |
| Talking to the agent | Real voice via LiveKit browser SDK | It's a voice agent; text-only would exercise none of the pipeline |
| Config storage | JSON files in `configs/` | Zero infra, greppable, committable. Behind a `ConfigStore` class so Postgres can replace it later without touching callers |
| Pipeline construction | **Per session, from room metadata** | The change that makes "edit config → Run again" work without restarting the worker |
| Tools | Named in the config, resolved from a registry | A tool is generic; the domain lives in its documents and the prompt. `knowledge_base` names no company |
| Embeddings | Pinecone integrated inference | One credential instead of two, and the ingest and query paths cannot disagree about dimensions |

## Providers

The provider list will keep growing. The design treats that as the normal case, not
as future rework: **supported** (a branch exists in the code) and **available**
(credentials are present) are two different things, and the UI only offers what is
both.

### Supported now

| Stage | Provider | Model / voice | Credential |
|---|---|---|---|
| STT | Deepgram | `nova-3`, `nova-2` | `DEEPGRAM_API_KEY` |
| LLM | Google | `gemini-3.5-flash-lite` (default) and 3 more | `GOOGLE_API_KEY` |
| LLM | Ollama | any local model | none — `OLLAMA_BASE_URL` |
| TTS | ElevenLabs | `eleven_flash_v2_5` + voice id | `ELEVEN_API_KEY` |
| TTS | Deepgram | 10 Aura-2 voices | `DEEPGRAM_API_KEY` |
| VAD | Silero | — | none, runs locally |
| Retrieval | Pinecone | `llama-text-embed-v2`, server-side | `PINECONE_API_KEY` |

**`gemini-2.5-flash-lite` is dead for new keys.** Google returns
404 "no longer available to new users" — while still listing it in
`/v1beta/models`, so the list endpoint is not a reliable source of truth. The four
models in `GEMINI_MODELS` were each verified with a real `generateContent` call on
2026-08-09. Re-verify with:

```bash
set -a; . ./.env; set +a
curl -s -X POST "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent?key=$GOOGLE_API_KEY" \
  -H 'Content-Type: application/json' -d '{"contents":[{"parts":[{"text":"Say OK"}]}]}'
```

Free-tier Gemini has per-model quotas; a burst of calls returns 429 with an empty
body, which reads like a network failure but is not.

### Known wart

`ConfigStore.list()` silently skips configs that no longer validate. Tightening a
`choices` tuple therefore makes existing saved configs *disappear from the UI*
rather than showing as broken. Worth fixing when the calls list lands in step 5.

Planned, not wired yet: OpenAI (STT/LLM/TTS), Cartesia (TTS), Groq, Azure. Nothing
about them needs designing now — see the recipe below.

### Adding a provider

Two touches, neither of which edits existing provider code:

1. **Catalogue entry** in `config/providers.py` — the fields that provider needs,
   their types, defaults, choices, and the env var that gates it:
   ```python
   "cartesia": ProviderSpec(
       name="cartesia", label="Cartesia", credential="CARTESIA_API_KEY",
       fields={"voice": FieldSpec(type=str, required=True),
               "model": FieldSpec(type=str, default="sonic-2")},
   ),
   ```
2. **Builder** in `pipeline.py`, registered against the same name:
   ```python
   @register_tts("cartesia")
   def _cartesia_tts(cfg: StageConfig) -> TTS:
       from livekit.plugins import cartesia

       return cartesia.TTS(voice=cfg.options["voice"], model=cfg.options["model"])
   ```

Plus the plugin dependency, if it is one we don't already pull in.

The UI needs **no change at all**: dropdowns, the fields under each, number-vs-text
inputs, defaults, and the disabled "needs CARTESIA_API_KEY" state all come from
`GET /api/providers`, which is generated from the catalogue.

A test asserts the two lists stay in step — see the drift guard under step 3.

### Dropped along the way

`build_chat_model()` and LangChain: they build a LangGraph chat model, a different
concern from the voice pipeline, unused here. Re-add under an `agents/` module if
LangGraph work starts.

`pyyaml`: prompts are inline in the config JSON, so `load_instructions()` is gone.

`livekit-plugins-openai` **is** installed despite OpenAI not being enabled — Ollama
is driven through it via `LLM.with_ollama()`, which talks to Ollama's
OpenAI-compatible endpoint.

## Where we are now (2026-08-17)

Steps 1-5a are in, including retrieval tooling and call logging. Nothing from the original
repo's code survives except in spirit — `pipeline.py` and `agent.py` were rewritten
around the config.

Pushed to <https://github.com/SameerSingh2901/conversational-ai-project>.
Full walkthrough in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

```
src/voice_agent/
├── __init__.py      placeholder hello()
├── config/          providers, errors, schema, store, env
├── api/             app.py + routes/{providers,configs,sessions}.py
├── pipeline.py      provider registry; every builder takes a StageConfig
├── agent.py         worker; config from room metadata, env var as fallback
├── tools/           registry + knowledge_base, the first real tool
├── rag/             documents, chunking, Pinecone store, ingest
├── calls/           call records: models, recorder, store, redaction seam
├── db/                                          still empty
└── app/…                                        stale empty dirs, safe to delete
ui/                  index.html, app.js, logs.html, logs.js, styles.css, vendor/
configs/             saved agent profiles, incl. spinny-support (uses the tool)
call_logs/           one record per call — gitignored, runtime data
knowledge/           source documents for the knowledge_base tool
docs/ARCHITECTURE.md file-by-file walkthrough, traces, invariants, traps
scripts/             make_sample_pdf.py — regenerates the demo document
```

~3,800 lines of source, 61 tracked files, **150 tests**, `make check` green.

**All four done-criteria are met.** Call overviews are recorded and viewable; what
is left is depth rather than capability:

- **Per-turn latency** is not captured yet. Overviews record totals; the breakdown
  (end-of-utterance delay, LLM time-to-first-token, TTS time-to-first-byte,
  correlated by `speech_id`) is step 5b.
- **Transcripts are not persisted.** They render live but nothing is stored, which
  is why `calls/redaction.py` is still a no-op.
- **`metrics_collected` is deprecated.** LiveKit now points at
  `session_usage_updated` for totals and `ChatMessage.metrics` for per-turn latency.
  Ours still works and records correct numbers; migrating is deliberately paired
  with 5b so the change can be watched on a real call.
- **`CallStore` does not scale.** One JSON file per call, and `list()` reads every
  one. Fine for development, wrong past a few thousand calls — see the scale
  section in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
- Retrieval costs ~1.2 s per lookup from India to Pinecone's `us-east-1`, on top
  of LLM and TTS time. Unaddressed.
- `tools` is a list of names; per-tool options (index, `top_k`, threshold) are
  constants. The natural extension is objects rather than strings.
- `dotenv` in `pyproject.toml` is a shim package — should be `python-dotenv`.
- The stale empty `src/voice_agent/app/` dirs are still there.
- Two commands (`make ui`, `make worker`) rather than one — step 6.

## Target architecture

```
src/voice_agent/
├── config/
│   ├── providers.py  DONE — the catalogue everything reads
│   ├── schema.py     DONE — AgentConfig + parse_config()
│   ├── store.py      DONE — ConfigStore over configs/*.json
│   └── env.py        DONE — credential gating
├── pipeline.py       DONE — provider registry
├── tools/
│   ├── registry.py   DONE — name → tool
│   └── property_tool.py    optional example, not copied over
├── agent.py          DONE for env-var config; step 4 adds room.metadata
├── logging.py        structured JSON to stdout (step 5)
├── calls/            call record model + store (step 5)
└── api/
    ├── app.py        DONE
    └── routes/       providers, configs DONE; sessions, calls to come
configs/              saved agent profiles
call_logs/            per-call transcript + latency records (step 5)
ui/                   plain HTML/CSS/JS, served by FastAPI
```

Request flow once complete:

1. UI `GET /api/providers` → dropdown options, generated from the catalogue
2. Save → `POST /api/configs` → validated → `configs/<name>-<YYYYMMDD-HHMMSS>.json`
3. Run → `POST /api/sessions {config_id}` → API creates a LiveKit room carrying the
   config in room metadata, returns `{url, token}`
4. Browser connects with `@livekit/components-react`, mic goes live
5. Worker picks up the job, reads metadata, builds **that session's** pipeline
6. Edit + Save + Run again → new pipeline, worker never restarts

---

# Steps

Each step is independently completable and has a concrete "done when" you can
check yourself. Don't start the next one until the current one passes.

## Step 1 — Config schema and store (backend only, no UI) — DONE

Built with the standard library only. No new dependencies were added.

- [x] `config/providers.py` — the provider catalogue. One `ProviderSpec` per
      provider, each declaring its fields, types, defaults, choices, and credential.
      Single source of truth for validation, the UI, and (later) the pipeline
- [x] `config/errors.py` — `FieldError(loc, msg)` and `ConfigValidationError`
      carrying *all* errors, shaped like pydantic's so the swap is invisible upstream
- [x] `config/schema.py` — `AgentConfig`, `StageConfig`, `PromptConfig` dataclasses
      plus `parse_config()`, the one and only raw-dict → object choke point
- [x] `config/store.py` — `ConfigStore.save/load/list/load_file`,
      `configs/<slug>-<YYYYMMDD-HHMMSS>.json`, newest first, invalid files skipped
- [x] `config/env.py` — `available_providers()` and `missing_credentials()`;
      supported vs available split
- [x] `tests/test_config.py` — 29 tests, including parsing the sample file unchanged

**Done:** 29 passed, ruff clean, mypy strict clean on `src/voice_agent/config`.

## On pydantic — deferred, not skipped

**Not necessary from the start.** What pydantic gives is validation, JSON Schema
generation, and FastAPI request parsing. The first two are hand-rolled above in
~250 lines; the third is not needed until step 2.

**It can be added later cheaply, because of one design choice:** `parse_config()`
is the single place raw JSON becomes an object, and `ConfigValidationError.errors`
is a list of `(loc, msg)` — exactly pydantic's `ValidationError.errors()` shape. So
the swap replaces the body of `schema.py` and leaves the store, the API, the
pipeline, and the UI untouched. `providers.py` becomes the union of provider models
and `describe_stages()` becomes `model_json_schema()`.

**The natural moment is step 2**, because FastAPI *is* pydantic — installing FastAPI
installs it whether we use it directly or not. At that point using it costs nothing
extra.

**What it costs to keep hand-rolling:** every new validation rule (ranges on
temperature, URL formats, cross-field checks) is code we write and test ourselves.
That bill grows slowly at first and then all at once.

## Step 2 — UI that saves and loads configs — DONE

Run it: **`make ui`** → http://localhost:8000

- [x] Added `fastapi`, `uvicorn` (+ `httpx2` dev, needed by starlette's TestClient).
      Pydantic still not used by our code — request bodies are read as raw JSON and
      handed to `parse_config()`, so there is one validator, not two
- [x] `GET /api/providers` — the catalogue from `describe_stages()`, each entry
      annotated with `available` based on which credentials are present
- [x] `GET /api/configs`, `GET /api/configs/{id}`, `POST /api/configs` (201),
      `POST /api/configs/validate` (checks without saving), `GET /api/health`
- [x] 422 responses carry `{"errors": [{"loc": [...], "msg": "..."}]}`; malformed
      JSON bodies give 400 in the same shape
- [x] `ui/` — plain HTML/CSS/JS, no build step, served by FastAPI itself. Sidebar of
      saved configs, name field, four stage sections, prompt textarea, Save
- [x] `make ui` target
- [x] `tests/test_api.py` — 24 tests

**Deviation from the plan:** the UI is vanilla JS, not Vite + React + TS. A build
toolchain, a second dev server, and a CORS/proxy setup are a lot of moving parts for
three dropdowns and a textarea, and one process instead of two is closer to the
one-command goal. Revisit at step 4 if the LiveKit call UI outgrows it.

**Verified:** 53 tests pass; ruff and mypy strict clean on `config/` and `api/`;
live server returns the provider catalogue, serves the page at `/`, and rejects a
broken config with five located field errors in one response.

### Note on the stage sections

The UI hardcodes nothing about providers. Dropdowns and the fields under them are
built from `GET /api/providers` at page load, so a new entry in
`config/providers.py` appears in the browser with no JS change. That is the property
worth protecting when this page grows.

## Step 3 — Run a saved config from the terminal — DONE

Run it: **`make agent CONFIG=<id>`** (`make configs` lists the ids)

- [x] Added `livekit-plugins-{deepgram,google,elevenlabs,openai,silero}`
- [x] `pipeline.py` rewritten as a registry — `@register_stt("deepgram")` etc. Every
      builder takes its own `StageConfig`; no module globals anywhere
- [x] Plugin imports stay at **module level**. LiveKit calls
      `Plugin.register_plugin()` at import and refuses to do it off the main thread;
      builders run in the job runner thread, so importing lazily inside a builder
      crashes on the first session with "Plugins must be registered on the main
      thread". Two tests pin this down
- [x] `tools/registry.py` — `@register_tool(name)` + `resolve_tools(names)`.
      Registry is empty, and `"tools": []` runs fine. Nothing use-case-specific
      is imported by the worker any more
- [x] `agent.py` — `ConfiguredAgent` takes instructions and tool names from the
      config. Which config comes from `VOICE_AGENT_CONFIG` (an id or a path)
- [x] Restored `src/voice_agent/py.typed`
- [x] `tests/test_pipeline.py` — 12 tests, including the drift guard below
- [x] Verified by holding an actual voice conversation with
      `make agent CONFIG=<id>`.
mypy strict). 66 tests pass. All four components construct against the real
plugins from the sample config — Deepgram STT, Google LLM, ElevenLabs TTS, Silero
VAD — and the Ollama LLM and Deepgram TTS branches construct too.

### The drift guard

`pipeline.unregistered_providers()` reports catalogue entries with no builder, and
a test asserts it is empty. A second test asserts the reverse. That covers the only
coupling in the design: a provider added to `config/providers.py` without a builder
(or vice versa) fails the suite instead of failing at call time.

### Why an env var, not a `--config` flag

LiveKit owns the command line here — `console`, `dev`, `start` are its subcommands,
and adding flags means fighting its parser for no benefit. Step 4 replaces the env
var with per-room metadata; `resolve_config()` is the one function that changes.

## Step 4 — Run a config from the UI — DONE

Two terminals:

```
make ui       # http://localhost:8000
make worker   # connects to LiveKit Cloud, waits for rooms
```

Pick a config in the sidebar (or Save one), hit **Run**, allow the mic.

- [x] `POST /api/sessions {config_id}` — creates a LiveKit room with the whole
      config as **room metadata**, mints a scoped join token, returns
      `{url, token, room, config_name}`
- [x] `config/env.py` — `livekit_credentials()` plus `wss://` → `https://`
      conversion (browser joins over ws, server API speaks http)
- [x] `agent.py` — `config_from_metadata()` reads `ctx.room.metadata` and builds
      that session's pipeline; falls back to `VOICE_AGENT_CONFIG` when a room has
      no metadata. `main()` no longer demands a config, so one worker serves every
      config
- [x] UI — Run button, call panel, mute, hang up, and a live transcript fed by the
      `lk.transcription` text streams the agent publishes
- [x] LiveKit browser SDK **vendored** at `ui/vendor/livekit-client.umd.min.js`,
      not a CDN link: the page works offline and the version is pinned by the file
- [x] `make worker`; `tests/test_sessions.py` — 17 tests
- [x] Verified in the browser: Run connects, the agent replies, the transcript
      fills in, and a re-run with a changed config picks it up with no restart.

**Verified:** 91 tests, `make check` green. Against real LiveKit Cloud, `POST
/api/sessions` returned 201, created room
`ollamaconfig-20260809-154922--93379d4e`, and reading that room back from LiveKit
parsed its metadata straight into the right `AgentConfig` — llm `ollama/llama3.1`,
tts `elevenlabs`, the prompt intact. The token grants `roomJoin` on that one room
only.

### Why the worker takes no config

`make worker` deliberately runs with `VOICE_AGENT_CONFIG` unset. Each call carries
its own config, so editing a config and hitting Run again picks up the change with
no restart — the thing the whole per-session design exists for. Setting the env var
still works and pins the worker to one config, which is what `lk agent console`
uses.

### Read metadata from the job, not the room

`ctx.room.metadata` is **empty inside the entrypoint** — the room object has not
connected yet at that point. The room record arrives with the job assignment, so
the metadata lives at `ctx.job.room.metadata`. `room_metadata(ctx)` prefers that
and falls back to `ctx.room`. Reading the wrong one made every UI-started call
crash with "VOICE_AGENT_CONFIG is not set", because the fallback path fired.

### Metadata that isn't ours

`config_from_metadata()` returns `None` for absent, non-JSON, or foreign metadata
so another tool's rooms don't break the worker — but **raises** when the metadata
looks like ours and fails validation, because starting a call with a silently wrong
agent is worse than failing.

## Step 4b — Retrieval tooling — DONE

Not in the original plan. Added to answer a real question: does the tools half of
the config design actually work end to end?

Run it: **`make ingest`**, then a config whose `tools` list contains
`"knowledge_base"`.

- [x] `rag/documents.py` — read PDF/markdown/text, chunk by section keeping the
      heading inside the chunk, fall back to overlapping size chunks when a
      document has no detectable structure
- [x] `rag/store.py` — Pinecone with **integrated embedding** (text in, text out).
      One credential, and no way for the ingest and query paths to disagree about
      embedding dimensions — a failure that shows up as poor recall, not an error
- [x] `rag/ingest.py` + `make ingest` — creates the index on first run; stable
      chunk ids mean re-running replaces rather than duplicates
- [x] `tools/knowledge_base.py` — the first real tool. Generic: nothing about cars
      or any company is in its code
- [x] `knowledge/spinny-policies.pdf` — 10-section sample document, marked as demo
      data inside the PDF itself so the disclaimer survives into retrieved chunks.
      `scripts/make_sample_pdf.py` regenerates it
- [x] `configs/spinny-support-*` — a config wired to the tool, with a prompt that
      forbids stating policy from memory
- [x] `tests/test_rag.py` — 28 tests, none of which touch the network

**Verified end to end against Gemini:** the model calls the tool for policy
questions, answers from the retrieved passages ("You have five days from
delivery…", numbers spoken as words), and declines off-topic questions without
calling it at all.

### The three things that make a tool usable in a voice call

1. **A relevance floor.** Vector search always returns its nearest neighbours, even
   for nonsense. Measured on the sample document: on-topic top hits score
   0.20–0.51, off-topic 0.03–0.09, so 0.15 sits in the gap. Below it the tool tells
   the model to say it does not know. A confidently wrong policy is worse heard
   than read — the caller cannot skim and check.
2. **`asyncio.to_thread`.** The Pinecone SDK is synchronous; calling it inline
   blocks the event loop that is also moving audio frames.
3. **Degrade, do not raise.** An exception inside a tool ends the call.

### Two traps

**The score key is `score_`, not `_score`.** Every hit came back as `0.000`, so the
relevance floor would have rejected everything — the agent saying "I don't have
that" to every question while retrieval worked perfectly. A parsing bug that looks
exactly like a retrieval failure. A test now pins both spellings.

**Registration happens at import.** A tool module that is never imported is never
registered, and the config fails with "unknown tool" even though the code exists
and its own tests pass. The import in `tools/__init__.py` is load-bearing.

## Step 5a — Call overview logs — DONE

The first slice: when a call ran, which config produced it, and what it cost.

- [x] `calls/models.py` — `CallRecord`, `CallTotals`, `TokenUsage`, `ToolUse`, plus a
      forgiving `record_from_dict()` so a record from a newer version stays listable
- [x] `calls/recorder.py` — subscribes to `metrics_collected`,
      `conversation_item_added`, `function_tools_executed` and `error`. Every handler
      is defensive: a malformed metric loses a number, never a call
- [x] `calls/store.py` — `call_logs/<room-name>.json`, mirroring `ConfigStore`
- [x] `calls/redaction.py` — the single seam free text will pass through. No-op, and
      nothing calls it yet: this increment stores no caller speech
- [x] `agent.py` — writes on `ctx.add_shutdown_callback`, **not** a `finally` in the
      handler, which would fire while the call was still running
- [x] `GET /api/calls`, `GET /api/calls/{id}` — read-only by design
- [x] UI: an "After the call" section between the controls and the transcript,
      showing *Generating logs…* while polling, then duration/turns/tokens and a
      **View logs** button that opens `/logs.html?call=<id>` in a new tab
- [x] `ui/logs.html` + `logs.js` — the log on its own page, so it is linkable
- [x] `tests/test_calls.py` — 23 tests, no network
- [x] `call_logs/` gitignored — runtime data that will hold caller speech

**Verified:** 146 tests, `make check` green. A simulated call with a tool round trip
records both LLM requests, 3,593 tokens (1,024 cached), 212 TTS characters, 4.8 s of
STT audio and one `knowledge_base` call.

### Decisions

**The room name is the call id.** Unique per call, and the browser already has it
from `POST /api/sessions`, so no second identifier has to be threaded through.

**The config is snapshotted into the record**, not referenced by id — the saved
config may be edited or deleted afterwards, and a record that pointed at it would
silently start describing something else.

**The API can only read.** No endpoint creates or edits a record. A call log the
application can rewrite is not worth much as a record of what happened.

**The browser polls.** The worker writes on shutdown, a moment after the browser
disconnects, so the record does not exist when the UI first asks. It polls for up to
20 s rather than guessing at a fixed delay — which is why `GET /api/calls/{id}`
returning 404 has to mean "not yet".

### Fixed while testing 5a

**The record landed 24 s after hang-up.** `add_shutdown_callback` guarantees the
write happens but not *when* — LiveKit uploads its session report first. In a real
call the session closed at 11:47:21 and the job did not shut down until 11:47:45,
by which point the browser had stopped polling and shown "No log was written". Now
written on `session.on("close")`, with the shutdown callback kept as a fallback and
a guard so it writes exactly once.

**Calls were silent.** ElevenLabs returns HTTP 402 for *shared library* voices on
free accounts, and LiveKit reports that as `no audio frames were pushed for text` —
a billing error wearing a synthesis error's clothes. The default voice was Rachel,
a library voice. Now Sarah (`EXAVITQu4vr4xnSDxMaL`), which is in the account's own
library; verified through `build_tts` at 12 frames / 1.57 s of audio. Voice ids are
per-account — `GET /v2/voices` lists yours.

**"Generating logs…" never stopped.** `.artifacts-pending` sets `display: flex`,
and an author-level display beats the UA stylesheet's `[hidden] { display: none }`,
so `element.hidden = true` did nothing. Fixed globally with
`[hidden] { display: none !important }`.

**The log page was a dashboard.** Cards, big stat numbers, a 900 px column and JSON
that scrolled sideways. Rebuilt as a log: monospace, aligned label/value rows, full
width, wrapping JSON, no horizontal scroll anywhere.

**A deleted config left an open page broken.** `POST /api/sessions` returned 404
while the sidebar kept offering the config. The page now clears the stale
selection, says so, and reloads the list.

**The model called a tool that was not enabled.** Running a config with
`"tools": []` while the prompt instructed a lookup produced
`unknown AI function knowledge_base` — and a confident, ungrounded answer. The
record captured it as `calls 1, errors 1`; the log page now says in words that the
answer was not grounded.

## Step 5b — Per-turn latency and transcripts

Everything 5a left out. The overview answers "what did this call cost"; this
answers "where did the time go, and what was actually said".

- [ ] Migrate off `metrics_collected` — LiveKit deprecated it in favour of
      `session_usage_updated` for totals and `ChatMessage.metrics` for per-turn
      latency. Pair the migration with this step so it can be watched on a real
      call rather than asserted against a guessed event shape
- [ ] Correlate metrics into turns by `speech_id`, which `EOUMetrics`, `LLMMetrics`
      and `TTSMetrics` all carry. Per turn: end-of-utterance delay, transcription
      delay, LLM time-to-first-token, TTS time-to-first-byte, and the derived
      caller-stopped-talking → agent-started-speaking total
- [ ] `llm_calls` as a **list** per turn — a tool-using turn makes two model calls,
      and modelling it as one understates both cost and latency
- [ ] Persist the transcript from `ConversationItemAddedEvent`, and route every
      string through `calls/redaction.py` — this is the increment where that seam
      stops being decorative
- [ ] Tool detail: duration and, for `knowledge_base`, the passages and scores
      returned. `FunctionToolsExecutedEvent` has neither, so the tool reports it
      itself via `RunContext.userdata`
- [ ] Log page: a per-turn latency table and the transcript alongside it
- [ ] A calls list in the UI, so you can compare turns across config revisions

**Done when:** after a call you can see which provider was slow on which turn, and
read what was said next to it.

## Step 6 — One-command startup and polish

- [ ] Single `make dev` (or docker-compose) bringing up API + worker + UI together
- [ ] README quickstart
- [ ] Delete the stale `src/voice_agent/app/` empty dirs

**Done when:** fresh clone → at most two commands → working app on a landing page
where you can create a new config or load a previous one.

---

## Not in scope yet

Postgres and Alembic (the `ConfigStore` interface is the seam for it), auth, RAG
ingestion, telephony/SIP, multi-user tenancy, deployment.

## Open questions

- LiveKit Cloud or self-hosted? Affects only `.env`, not code.
- Should latency thresholds raise warnings in the UI, or is the table enough for now?
- Free-tier ElevenLabs has low monthly character limits and tight concurrency —
  long test calls will exhaust it. Worth watching during step 4.
