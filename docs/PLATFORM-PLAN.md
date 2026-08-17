# Platform plan

From a working demo to a business that charges money. What survives from what is
built, what has to be replaced, how it runs on AWS, and the shortest honest path to
a first paying customer.

Companion to [`ENGINEERING-PLAN.md`](ENGINEERING-PLAN.md), which covers *how* to
build it. Rendered version: `claude.ai/code/artifact/397c5a1b-1d9b-4816-8ac9-eff04df6d926`

---

## 0. The first question

Building the platform is not the fastest way to earn from it.

The product described — sign up, buy credits, build an agent, connect a CRM, make
real calls, review them — is roughly **eight capabilities**, and the ones that make
it a *business* (accounts, payments, telephony, compliance) have none of the
existing work in them.

| Path | Build first | First rupee | Risk |
|---|---|---|---|
| **Self-serve** | Auth, billing, credits, onboarding, agent builder, telephony, call review — before anyone can pay | 3–6 months | You learn whether anyone wants it *after* building all of it |
| **Concierge** | Telephony + call records only. Onboard 1–3 customers by hand, run their agents, invoice monthly | **3–6 weeks** | Does not scale past ~10 customers — by design |

The concierge path is not a lesser plan. It is the same plan in an order where
customers pay for the parts as they are built. The hard half already exists: a
working config-driven pipeline with retrieval and call logging. What is missing is
a phone number and an invoice.

## 1. Capability map

Each module is independently testable and could ship alone. **Module ids are fixed
and must not be renamed** — specs, branches and tickets refer to them.

| Module | Responsibility | Depends on | Exists today |
|---|---|---|---|
| `identity` | Accounts, login, sessions, API keys, isolation | — | none |
| `agents` | Agent definitions, versioning, provider catalogue, test console | identity | **most of it** |
| `knowledge` | Per-account document ingestion and retrieval | identity, agents | **most of it** |
| `telephony` | Phone numbers, inbound/outbound PSTN, call control | agents | none |
| `calls` | Records, transcripts, recordings, traces, search | agents, telephony | **the record layer** |
| `billing` | Credit balance, metering, top-up, spend limits, invoices | identity, calls | the meters |
| `integrations` | CRM read/write, webhooks, outcomes pushed back | calls | the tool registry |
| `console` | The customer-facing web app | all of the above | a prototype |

**Build order:** identity → agents, knowledge → telephony → calls → billing →
integrations → console.

Two observations. `telephony` turns a demo into a product and has none of the
existing work in it. And `billing` depends on `calls` — you cannot charge for what
you cannot measure, which makes the call logging commercially load-bearing, not
just diagnostic.

## 2. What survives

Everything that knows about *voice* survives. Everything that knows about *storage*
is replaced. That is what the layered dependency rule bought.

| Today | Verdict | Why |
|---|---|---|
| `config/providers.py` | **Keep** | The catalogue is exactly what a multi-tenant agent builder needs |
| `config/schema.py` | **Keep** | An agent definition is still a validated document. Gains `account_id` |
| `pipeline.py` | **Keep** | Per-session construction is precisely what multi-tenancy requires. Most valuable file in the project |
| `tools/registry.py` | **Keep** | Becomes the extension point for CRM tools |
| `agent.py` | **Keep** | Config-from-room-metadata already works for many tenants. Add authorisation before room creation |
| `calls/models.py` | Adapt | Add `account_id`, `agent_version_id`, recording pointer, per-turn detail |
| `rag/` | Adapt | Namespace per account; currently one global namespace from an env var |
| `config/store.py` | **Replace** | JSON files → Postgres rows with versioning and ownership |
| `calls/store.py` | **Replace** | JSON files → Postgres index + S3 payloads |
| `api/` | Extend | Auth, tenant scoping, pagination, filtering. The routes survive |
| `ui/` | **Replace** | A no-build prototype was right for one user |

**The line that pays off:** because `build_stt/llm/tts/vad` run *inside* the session
handler rather than at import, one worker already serves different agents for
different customers. That was a convenience decision; it happens to be the property
multi-tenancy needs.

## 3. Blockers in the current code

Three things break under many customers. None is a mistake — they are correct
decisions for a single-user tool. Each must close **before** a second customer.

1. **Cross-tenant leak.** `tools/knowledge_base.py` holds `_kb` as a module-level
   singleton, built once per process from an env-var namespace. With many accounts,
   the first namespace is cached and served to every later call in that process —
   customer A's documents answering customer B's caller. Fix: construct per call
   from the agent definition, reached through `RunContext.userdata`. Same plumbing
   as per-turn tracing, so do them together. See ADR-0009.
2. **Nothing is scoped to an owner.** Zero references to account, tenant or user in
   `src/`. Every store is scoped by a process env var.
3. **Listing is O(everything).** `CallStore.list()` parses every record ever
   written.

## 4. AWS design

```
CONTROL PLANE          console (CloudFront+S3) → API (ECS Fargate+ALB) → Aurora
                                                      │
                                                      ↓ create room, after credit check
DATA PLANE   PSTN → LiveKit Cloud (SIP+SFU) → agent workers (Fargate) → providers
                          │                          │
                          ↓ recording egress          ↓ call record via SQS
                         S3                          Aurora + S3
```

| Concern | Choice | Why |
|---|---|---|
| Web console | S3 + CloudFront | Static. No servers for the part customers use most |
| API | ECS Fargate behind ALB | Containers. Lambda is awkward for long-lived connections |
| Agent workers | ECS Fargate, scaled on LiveKit worker load | Long-lived processes holding audio sessions |
| SFU + SIP | **LiveKit Cloud** | Do not run media servers. Biggest "don't build it" on the list |
| Telephony | SIP trunk into LiveKit | Provider choice is a business decision — see compliance |
| Index | Aurora Postgres Serverless v2 | Every list and filter hits only this |
| Payloads | S3, lifecycle to Glacier | Recordings and transcripts: large, immutable, rarely read |
| Ingest | SQS + small consumer | A database outage degrades logging, not calls |
| Auth | Cognito, or Clerk/Auth0 early | Do not write password reset flows |
| Secrets | Secrets Manager (platform), KMS envelope (customer) | A breach of provider keys is a direct bill |
| Vectors | Pinecone, namespace per account | Already integrated; namespace is the tenant boundary |

The API never touches audio; the workers never serve a web request. Recordings go
from LiveKit to S3 without passing through your code.

## 5. Data model

| Table | Key columns |
|---|---|
| `accounts` | id, name, plan, credit_balance, spend_cap, concurrency_cap |
| `users` | id, account_id, email, role |
| `agents` | id, account_id, name, **published_version_id**, archived_at |
| `agent_versions` | id, agent_id, version_number, definition (JSONB), message, created_by, parent_version_id |
| `calls` | id, account_id, **agent_version_id**, direction, from/to, started_at, duration, outcome, meters, recording_key, transcript_key, credits_charged |
| `call_turns` | call_id, index, speaker, text, eou_ms, llm_ttft_ms, tts_ttfb_ms, tool calls |
| `credit_ledger` | account_id, delta, reason, call_id, balance_after |

Three rules that matter more than the columns:

- **`account_id` on every row**, filtered at the data-access layer, never in a
  handler. One forgotten `WHERE` is a data breach.
- **Agents are versioned and calls point at a version.** Editing an agent must not
  change what last week's calls appear to have run.
- **Credits are a ledger, not a number.** A balance alone cannot answer "why am I
  being charged this", and you will be asked.

## 6. Storage at scale

1,000 accounts × 10 agents × 1,000 calls = **10 million calls**, three minutes
average. Planning figures — verify prices before modelling margin.

| What | Per call | At 10M | Where |
|---|---:|---:|---|
| Recording (mono, compressed) | ~0.6 MB | ~6 TB | S3 → Glacier after 90 days |
| Transcript + traces | ~20 KB | ~200 GB | S3, or JSONB if queryable |
| Index row | ~0.5 KB | ~5 GB + indexes | Aurora |

**The index is tiny and the payload is enormous — that asymmetry is the design.**
Ten million rows is unremarkable for Postgres and answers a filtered, paginated
query in milliseconds given an index on `(account_id, agent_id, started_at DESC)`.
Six terabytes of audio is cheap to keep and expensive to scan.

The rule: **listing reads Postgres only; opening one call fetches from S3 by key.**
Recordings are served as time-limited presigned URLs so audio never transits the API.

Retention is the other half. At six terabytes a year of customer voice, "keep
everything forever" is a storage bill and a liability. Hot 90 days, Glacier to a
year, then delete unless the plan says otherwise — with a deletion path on request.

## 7. Unit economics

Selling credits means reselling provider capacity with a margin. That only works
with precise per-call, per-account metering.

| Meter | Billed by | Status |
|---|---|---|
| STT audio seconds | Deepgram | **already captured** |
| LLM tokens in/out | Google, OpenAI… | **already captured** |
| TTS characters | ElevenLabs, Deepgram | **already captured** |
| Telephony minutes | SIP trunk provider | not built |
| LiveKit participant minutes | LiveKit Cloud | not built |

**TTS and telephony dominate.** STT is cheap per minute and a Flash-tier LLM is
nearly free at conversational token volumes, but premium neural TTS is billed per
character and an agent speaks a lot of characters.

That reframes a feature already built: letting customers choose between ElevenLabs
and Deepgram Aura is not just flexibility, it is the main margin lever and a pricing
tier waiting to happen.

**Do not launch without a per-account spend cap.** A runaway agent in a loop is a
bill you pay, not the customer.

## 8. Compliance

Automated outbound voice calling in India is regulated. Treat this as the list of
questions for a telecom lawyer, not as answers.

- **Telemarketing registration and DND.** TRAI's unsolicited commercial
  communication rules govern who may call, whom, and when. Scrubbing against the
  do-not-disturb registry is not optional; calling hours are restricted.
- **Consent and disclosure.** Whether the callee must be told they are speaking to
  an AI, and whether recording requires an announcement, changes the agent's opening
  line — a product requirement, not a footnote.
- **Recordings and transcripts are personal data** under the DPDP Act. Retention
  limits, a deletion path, and an answer to "why do you have this" are obligations.
  `calls/redaction.py` exists for this.
- **Processor vs controller.** If a customer uploads a calling list, they are the
  controller and you are the processor. That needs a written agreement before you
  place a call on their behalf.

**Practical consequence: inbound is dramatically simpler than outbound.** A support
line customers' own callers dial into avoids most of the above, and it is what the
existing Spinny support agent already is.

## 9. Phases

Each phase ends with something a customer can use.

| Phase | Duration | Work | Done when |
|---|---|---|---|
| **1** | 1–2 wks | Close the three multi-tenant blockers. Per-call knowledge base, `account_id` threaded through, Postgres behind the store interfaces. Do per-turn latency here too — same plumbing, and billing needs the meters | Two accounts, neither can see the other's data |
| **2** | 2–4 wks | SIP trunk, inbound only, recording egress to S3, call list with filters. Then one business with an inbound support line, run by hand, invoiced monthly | **Money has arrived in a bank account** |
| **3** | 3–5 wks | Auth and accounts. Console rebuilt as a real front end. Customers do their own prompt iteration — where most manual time goes in phase 2 | A customer changes a prompt without emailing you |
| **4** | 2–4 wks | Metering into a ledger, top-up via payment gateway, spend caps, invoices, signup without you | Someone you have never spoken to pays and makes a call |
| **5** | ongoing | Outbound with its compliance work, CRM integrations, analytics | — |

## 10. Open decisions

| Decision | Why it changes the build |
|---|---|
| **Inbound or outbound first?** | Outbound is where the money and the regulation are. Inbound ships months sooner and is the existing demo. Recommend inbound |
| **Your provider keys or theirs?** | Credits imply yours: you carry provider cost, need spend caps, margin depends on TTS choice. BYOK removes all of that and most of the revenue |
| **Concierge first, or straight to self-serve?** | The whole phase order turns on this |
| **Who is the first customer?** | Not a segment — a name. Phase 2 is unblocked by a person who has agreed to try it |
| **Console stack** | Next.js on Amplify or Vercel is the boring, probably right answer |

---

**Shortest version.** The hard, differentiated half is built: a provider-agnostic
voice pipeline configured per call, with retrieval and metering. What stands between
that and revenue is not more pipeline — it is a phone number, an account boundary,
an indexed database, and one customer who has agreed to pay.
