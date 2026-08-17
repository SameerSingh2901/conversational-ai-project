# Engineering plan

Repository and workflow, what each piece of infrastructure is for and when it
arrives, the agent version-history design, and the security model — sequenced so
nothing is built before it is needed.

Companion to [`PLATFORM-PLAN.md`](PLATFORM-PLAN.md), which covers *what* to build
and why. Rendered version: `claude.ai/code/artifact/f11c4455-b0cc-4108-aac0-4c435a6086d1`

---

## 1. Horizontal means four catalogues

`config/providers.py` is a table describing every provider — fields, types,
defaults, and the credential that unlocks it — read by four separate consumers: the
validator, the browser form, the credential gate, and the pipeline builders.

A horizontal platform is that pattern applied **four times**.

| Catalogue | Entries | Handler | Today |
|---|---|---|---|
| **providers** | Deepgram, ElevenLabs, Gemini, OpenAI, Ollama, Cartesia, Groq, Azure… | `@register_tts("x")` | built |
| **tools** | knowledge base, calendar, order lookup, transfer to human, end call | `@register_tool("x")` | built |
| **integrations** | HubSpot, Salesforce, Zoho, Sheets, generic webhook, REST | `@register_integration("x")` | next |
| **channels** | web mic, inbound phone, outbound phone, WhatsApp later | `@register_channel("x")` | next |

The property to protect: **the console must never hardcode a provider name.** It
renders dropdowns, fields, defaults and disabled states from `GET /api/catalogue`.
Adding Salesforce ships no front-end change.

An integration entry declares its own credential fields — HubSpot needs a private
app token, Salesforce needs OAuth, a webhook needs a URL and signing secret —
exactly as `FieldSpec` already declares `voice_id` and `temperature`.

> **What makes an agent generic.** A car dealer and a factory differ in three
> things: the documents in their knowledge base, the text of their prompt, and which
> integrations they installed. None is code. If you ever write
> `if account.industry == "automotive"`, the catalogue has failed and the fix is a
> new entry, not a branch.

## 2. Agent version history

**The gap today:** every save mints a new id and never overwrites — the right
instinct — but there is no identity linking `spinny-support-…083427` and
`spinny-support-…084452` as the same agent. Each save produces a *separate* agent.

```
agents           id · account_id · name · published_version_id · archived_at
agent_versions   id · agent_id · version_number · definition (JSONB)
                 message · created_by · created_at · parent_version_id
calls            … · agent_version_id      -- not agent_id alone
```

```
   v1 ──→ v2 ──→ v3 ──→ v4
               published  draft
                  ▲
    call 3 Aug ───┘ (points at v2)
    call 17 Aug ──→ (points at v3)
```

Four rules make this version control rather than an audit log:

- **Snapshots, not deltas.** A definition is a couple of KB of JSON. Replaying
  diffs is real complexity for savings you do not need. Diffs are computed on read.
- **Rows are append-only.** No update, no delete. This is what makes "what did this
  call actually run" answerable forever.
- **Publishing is a pointer move; editing is a new row.** Drafts stop a
  half-finished prompt answering a live call — the most important safety property in
  the feature.
- **Rollback publishes an old version; it never rewinds.** Pointing
  `published_version_id` back at v2 leaves v3 and v4 intact. Git's revert, not reset.

The call binding is what makes it commercially useful: when a customer says "the
agent said something wrong last Tuesday", open the call, read `agent_version_id`,
and see the exact prompt — even after four edits since.

## 3. The secrets problem integrations create

Today `POST /api/sessions` writes the **entire** agent definition into LiveKit room
metadata. Elegant: the worker is stateless and the call is a snapshot. But once an
agent holds a HubSpot token, **you are writing your customer's credentials into a
third party's room record.**

The fix keeps the good property:

- Room metadata carries the definition with **credential fields replaced by
  references** — `{"integration": "hubspot", "credential_ref": "acc_123/hubspot"}` —
  plus a short-lived, single-room scoped token.
- The worker exchanges that token for the credentials over an authenticated call to
  the API, which decrypts per use.
- Customer credentials use envelope encryption: a KMS master key, a per-account data
  key. Platform provider keys live in Secrets Manager and never leave.

Worth designing before the first integration; retrofitting means rotating every
customer's tokens.

## 4. Repository and workflow

### Monorepo, uv workspaces

```
apps/
  api/          FastAPI control plane
  worker/       LiveKit agent worker
  ingest/       queue consumer that writes call records
  console/      Next.js front end
packages/
  core/         today's src/voice_agent — catalogues, schema, pipeline, tools, rag
  db/           SQLAlchemy models + Alembic migrations
infra/          Terraform, once the shape is known
docs/adr/       one file per architectural decision
```

Monorepo because a change to the agent definition schema touches the API, the
worker and the console at once, and that belongs in one reviewable commit.
Splitting repos buys independent deploys you do not need and costs atomic changes
you need constantly.

`packages/core` is the current codebase almost unchanged. It stays free of HTTP,
database and AWS — which is why the API and worker can both depend on it without
depending on each other.

### GitHub

| Setting | Why |
|---|---|
| Protected `main`, PRs only | One person now, three later. The habit predates the team |
| Required checks: lint, types, tests, migrations | All four already run in `make check`. Move them to CI |
| Squash merge, conventional commits | Keep the format enforced |
| Secret scanning + Dependabot + CodeQL | Free, and you are about to hold customer credentials |
| GitHub Environments: `staging`, `production` | Scoped deploy secrets; production gated on approval |
| `docs/adr/NNNN-title.md` | Six months from now you will not remember why LiveKit over Pipecat |

## 5. The stack, in arrival order

Every service added is one more thing to run, secure, pay for and debug at 2am.

| Piece | When | What forces it |
|---|---|---|
| **Postgres** | now | Listing is O(all records) and there is no owner column. Docker locally, RDS later. Alembic from the first table |
| **S3** | now | Recordings and transcripts do not belong in a row. LiveKit egress writes directly |
| **GitHub Actions** | now | Once more than one environment exists, "works on my laptop" stops being enough |
| **Docker** | now | The worker must run somewhere other than your machine |
| **Auth (Cognito/Clerk)** | at signup | Do not write password reset, email verification or session rotation |
| **SQS + ingest** | before launch | So a database outage degrades logging instead of dropping calls |
| **KMS** | first integration | The first time you hold a customer's CRM token |
| **Redis** | when measured | See below |
| **Terraform** | after staging works | Codify infrastructure once you know its shape, or write it twice |
| **ClickHouse** | at real volume | Only when cross-account analytics outgrow Postgres. Probably never in year one |

### What Redis is for, and why not yet

It earns its place for four things, none of which bite at low volume:

- **Credit reservation** — two concurrent calls must not both spend the last of a
  balance. An atomic decrement is clean, but `SELECT … FOR UPDATE` is correct too
- **Rate limiting** per account and per API key
- **Caching the published definition**, read once per call setup
- **Live-call registry**, for per-plan concurrency caps

All four work in Postgres first. Add Redis when a query shows up in the slow log,
not because the diagram looks incomplete.

## 6. Data model

Ten tables: `accounts`, `users`, `api_keys`, `agents`, `agent_versions`,
`integrations`, `knowledge_sources`, `calls`, `credit_ledger`, `audit_log`. Column
detail in [`PLATFORM-PLAN.md`](PLATFORM-PLAN.md) §5.

**The rule: `account_id` on every table, filtered at the repository layer — never in
a route handler.** Give every repository method the account as its first argument so
it is impossible to call without one. Postgres row-level security on top turns a
forgotten filter from a breach into an empty result set.

Index on `(account_id, agent_id, started_at DESC)` and paginate by keyset
(`WHERE started_at < $cursor`), not `OFFSET`, which degrades linearly as customers
accumulate history.

## 7. Security

| Risk | Control |
|---|---|
| **Tenant leakage** | Account scoping in the repository layer, RLS as backstop, and a test asserting account B cannot read A's calls, agents or documents. Write it before the second account exists |
| **Customer credentials** | Envelope encryption with KMS, decrypted per use, never logged, never in room metadata, rotatable per account |
| **Runaway spend** | Per-account spend and concurrency caps enforced *before* room creation. A compromised account otherwise spends your money |
| **Recording exposure** | Private buckets only. Short-lived presigned URLs after an authorisation check |
| **Personal data** | Retention windows, deletion endpoint, the redaction seam wired into transcript storage |
| **Prompt injection** | See below |

> **The AI-specific one.** A caller is an untrusted party who can say anything, and
> the agent hands their words to an LLM that can call tools. Once an integration can
> *write* — update a CRM record, book an appointment, issue a refund — a caller
> saying the right sentence is an attack.
>
> Controls: mark tools read or write in the catalogue; require write tools to be
> explicitly enabled per agent; constrain arguments with the same `FieldSpec`
> validation used for configs rather than trusting the model's JSON; scope each
> integration credential to the narrowest permission the vendor offers; log every
> write-tool invocation with the transcript turn that triggered it.

## 8. Speed

The number that decides whether the product feels good is **time from the caller
finishing a sentence to hearing the first syllable back**.

- **Instrument first.** Per-turn end-of-utterance delay, LLM TTFT, TTS TTFB, tool
  duration. You cannot budget what you cannot see
- **Colocate.** Workers, LiveKit region, Pinecone region and providers in one
  geography. The measured 1.2s retrieval was mostly a trip to `us-east-1`
- **Prewarm workers.** Measured 1.93s of process cold start; LiveKit's warm pool
  removes it from the first call
- **Cache the definition** — room creation reads the published version every call
- **Let the model speak sooner.** Streaming TTS on the first sentence is already how
  LiveKit behaves; do not undo it with post-processing
- **Keyset pagination and narrow indexes** so the call list stays fast at a million rows

Publish a target — **under 1.2s for a turn without a tool call, under 2.5s with
one** — and put the measured p95 on a dashboard. A latency number nobody watches
quietly gets worse.

## 9. Migration

Not a rewrite. Every step leaves the tests green.

1. **Move, don't change.** `src/voice_agent` → `packages/core`, `ui/` stays as an
   internal test console, `apps/` created empty. Pure file moves and import updates.
   *Verify: all tests still pass.*
2. **Introduce the database behind the interfaces you already have.** Alembic, the
   ten tables, Postgres implementations of `ConfigStore` and `CallStore`. Callers
   untouched because signatures do not change. *Verify: the same store tests pass
   against Postgres via testcontainers.*
3. **Split agent identity from agent version.** §2's schema. Existing config files
   import as one agent with one version each. *Verify: a call records its version,
   and editing an agent leaves old calls reading the old definition.*
4. **Thread `account_id` through everything.** Repository methods take it first. The
   knowledge-base singleton is replaced by per-call construction. Pinecone namespace
   becomes the account. *Verify: the cross-tenant test.*
5. **Auth, then the console.** Next.js replaces the prototype, rendering every form
   from the catalogue endpoint. *Verify: a second account signs up and creates an
   agent without you touching a file.*

## 10. Build sequence

| Wk | Work | Done when |
|---|---|---|
| 1 | Monorepo move, CI on PRs, first ADRs, Dockerfiles | A PR cannot merge with failing lint, types or tests |
| 2–3 | Postgres + Alembic; stores swapped; S3 for payloads | Configs and calls live in the database; listing is a paginated query |
| 4 | Agent/version split, draft and publish, version diff endpoint | An agent has a history and a call names its version |
| 5 | `account_id` everywhere, per-call knowledge base, RLS, cross-tenant test | Two accounts provably cannot see each other |
| 6 | Per-turn tracing, transcripts through the redaction seam, the five meters | A call log shows where every millisecond and rupee went |
| 7–8 | SIP trunk, inbound number, recording egress, staging on AWS | A real phone call reaches a real agent and leaves a full record |
| 9–11 | Auth, Next.js console, catalogue-driven forms | Someone who is not you signs up and builds an agent |
| 12–13 | Integrations catalogue + first CRM, KMS credentials, write-tool controls | An agent updates a record in a customer's CRM, safely |
| 14+ | Credits, metering, payments, spend caps | Money arrives without you sending an invoice |

**Weeks 1–6 are all in the existing repository** and need no AWS account, no payment
gateway and no customer. Week 7 is the first that needs money and a phone number. If
revenue is wanted earlier, weeks 7–8 can move ahead of 4–6 and be run by hand for
one customer.

## 11. What to resist

| Temptation | Why not |
|---|---|
| Kubernetes | Fargate runs containers without a control plane to operate |
| Microservices | Four apps in one repo sharing one core package. Boundaries before you know the domain produce distributed monoliths |
| Self-hosting LiveKit | Running media servers is a company in itself |
| An abstraction over Postgres and DynamoDB | You will use one database. Pick Postgres |
| Building CRM integrations before a customer names one | There are forty. Build the one your first customer uses |
| A plugin marketplace / customer-supplied code | Arbitrary customer code in your worker is a security model you are not ready to own |
| Rewriting the pipeline | It is the best code in the project and already does what multi-tenancy needs |

---

**The through-line.** Every hard part is a variation on something already in the
codebase. Multi-tenancy is the per-session pipeline with an owner attached. Agent
history is the never-overwrite config store with an identity added. The integrations
catalogue is the provider catalogue again. The security model is mostly making
`account_id` impossible to forget. Extension, not reinvention.
