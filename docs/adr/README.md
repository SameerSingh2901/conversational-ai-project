# Architecture decision records

One file per decision: the context, what else was considered, what was chosen, and
what it cost. Written so a reader six months from now — or a fresh session with no
memory of the conversation — can tell whether a decision still holds.

Status is `Accepted` (in the code today), `Proposed` (planned, not built), or
`Superseded by NNNN`.

| # | Decision | Status |
|---|---|---|
| [0001](0001-livekit-as-voice-runtime.md) | LiveKit Agents as the voice runtime | Accepted |
| [0002](0002-catalogue-driven-configuration.md) | One provider catalogue, four consumers | Accepted |
| [0003](0003-per-session-pipeline.md) | Build the pipeline per session, not at import | Accepted |
| [0004](0004-config-in-room-metadata.md) | The config travels as LiveKit room metadata | Accepted |
| [0005](0005-defer-pydantic.md) | Hand-rolled validation; pydantic deferred | Accepted |
| [0006](0006-pinecone-integrated-embeddings.md) | Pinecone with server-side embeddings | Accepted |
| [0007](0007-call-record-on-session-close.md) | Write the call record on session close | Accepted |
| [0008](0008-file-stores-behind-interfaces.md) | File-based stores behind a swappable interface | Accepted |
| [0009](0009-multi-tenancy-model.md) | Multi-tenancy: account_id at the repository layer | Proposed |
| [0010](0010-agent-versioning.md) | Agent version history: append-only versions | Proposed |
| [0011](0011-monorepo.md) | Monorepo with uv workspaces | Proposed |
