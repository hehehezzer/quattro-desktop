# Persistent memory database specification

`memory.sqlite3` is independent of the derived repository knowledge index. No entire conversation is automatically persisted. Memory creation is explicit, attributed to the configured principal and unverified by default.

## Schema version 1

| Table | Columns / purpose |
|---|---|
| `memories` | `id` stable UUID-style ID; `project`; `category`; `content`; normalized `content_hash`; `author`; `references_json`; `confidence`; `verification`; `tags_json`; `metadata_json`; `visibility`; nullable `fact_key`; UTC `created_at`/`updated_at`; integer `revision`; `state`; `invalidation_reason`; `superseded_by` foreign key |
| `memory_fts` | FTS5 `id` unindexed, `content`, `tags`, `metadata`; active recall joins authorized records |
| `memory_events` | Monotonic `sequence`; `memory_id`; `project`; `operation`; `actor`; UTC `occurred_at`; `snapshot_json` |

Indexes cover namespace/state/visibility/author and namespace/fact-key/state. `PRAGMA user_version=1` identifies this schema. Unknown nonempty databases and future versions are rejected without deleting records. Initialization is serialized with `BEGIN IMMEDIATE`.

Categories: `episodic` (outcomes/investigations/failed approaches), `semantic` (facts/decisions/constraints), `procedural` (workflows/lessons), `shared` (authorized cross-session publication). All remain scoped to one project; `shared` does not mean globally readable.

## Validation and trust

- Content: nonempty, at most 24,000 UTF-8 bytes; complete validated record at most 32,000 UTF-8 bytes. MCP additionally limits content to 16,384 characters and total request frames.
- Confidence: finite 0–1. Verification: `unverified`, `verified` or `disputed`. Verified records require source references and the transport's `can_verify` capability.
- References/tags: at most 50 nonblank strings each, at most 1,000 characters per string. Metadata is a JSON object; non-finite values, credentials and oversized data fail.
- Credential detection scans content, all nested string values/keys, references, tags and serialized JSON, including bounded escaped/Unicode representations. This is defensive pattern detection, not a guarantee that arbitrary sensitive prose is recognizable.
- `visibility: project` permits authorized project principals. `private` permits only the configured author, including recall, mutation and statistics. MCP callers cannot impersonate an author or change visibility through updates.
- References are evidence identifiers, not executable links. A caller's verification flag does not independently prove truth; trusted verification permission and evidence review remain operator responsibilities.

## Lifecycle

Create → active record, revision 1, audit snapshot. Identical normalized content in the same project/visibility/private-author scope returns the existing active record without silently escalating confidence or verification. Fact identity is checked before deduplication; a duplicate cannot bypass a contradiction or acquire another fact key. Deduplication does not perform fuzzy semantic merging.

Update → atomic expected-revision check, validation, revision increment and event. Verification permission applies to the resulting record, including updates to already verified records. Once assigned, `fact_key` cannot be cleared or renamed. Content of an active fact cannot be replaced in place.

Supersede → create a new record with `supersedes` and the same fact key. The old record becomes `superseded`, links to the new ID and disappears from ordinary recall. Competing active values for the same accessible fact key are rejected. Private facts belonging to another principal do not disclose their presence through a conflict error.

A new topic is not a replacement for an unrelated fact. Save it separately
without `supersedes`; do not rename a fact or drop supersession merely to bypass
a same-fact conflict. Rejected state, identity and revision transitions retain
their transactional rollback and return stable conflict codes with safe context
from accessible records. Inaccessible private IDs remain indistinguishable from
missing IDs. The operator CLI prints the trusted conflict code and guidance;
native/MCP response fields and genuine availability failures are documented in
[the integration contract](INTEGRATION.md#safe-operation-failures). No boundary
automatically rewrites a failed request or retries its mutation.

Invalidate → mark `invalid`, retain reason/history and remove from ordinary recall. Historical retrieval is explicit; `memory history --project PROJECT ID` authorizes the record before exposing retained revision snapshots. Delete → remove the record, FTS row and content-bearing event history. Deletion is logical, not guaranteed forensic erasure from SQLite free pages, WAL or backups.

## Freshness and contradictions

Prefer current source evidence to older/unverified observations. Context compares explicit `Fact: key=value` declarations, flat structured configuration and memory `metadata.claims`. Conflicts identify evidence IDs and a preference; contradictory/disputed memories are not assembled as current facts. Source authority determines preference, with repository evidence winning equal-authority ties. Missing/changed source evidence is suppressed until reconciled; invalidated/superseded memory remains available only through explicit historical inspection.

This is not general natural-language truth detection. Use stable `fact_key` values, explicit claim metadata, references and supersession for important facts. Ordinary prose must still be reviewed by the client.

## Integrity and recovery

WAL, full synchronization, foreign keys and lock timeouts protect independent connections. Deduplication, conflict/revision checks, state transitions, FTS and audit events commit together. Indexing does not mutate memory. `doctor` uses genuinely read-only connections and checks integrity without initializing or repairing schema. Private multi-database backup includes committed WAL, source mappings, vectors, feedback, history and receipts; checksummed isolated restore validates schema/authorization/integrity and source links before recording recovery. See [operations](installation.md#backups-and-compatible-legacy-import) and [migration](MIGRATION.md). Verification permission and references are provenance gates, not automatic semantic proof.
