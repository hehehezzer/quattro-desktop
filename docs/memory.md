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
- References/tags: at most 50 strings each, at most 1,000 characters per string. Metadata is a JSON object; non-finite values, credentials and oversized data fail.
- Credential detection scans content, all nested string values/keys, references, tags and serialized JSON, including bounded escaped/Unicode representations. This is defensive pattern detection, not a guarantee that arbitrary sensitive prose is recognizable.
- `visibility: project` permits authorized project principals. `private` permits only the configured author, including recall, mutation and statistics. MCP callers cannot impersonate an author or change visibility through updates.
- References are evidence identifiers, not executable links. A caller's verification flag does not independently prove truth; trusted verification permission and evidence review remain operator responsibilities.

## Lifecycle

Create → active record, revision 1, audit snapshot. Identical normalized content in the same project/category/visibility/private-author scope returns the existing active record. Fact identity is checked before deduplication, so a duplicate cannot bypass a contradiction or acquire a different fact key.

Update → atomic expected-revision check, validation, revision increment and event. Verification permission applies to the resulting record, including updates to already verified records. Once assigned, `fact_key` cannot be cleared or renamed. Content of an active fact cannot be replaced in place.

Supersede → create a new record with `supersedes` and the same fact key. The old record becomes `superseded`, links to the new ID and disappears from ordinary recall. Competing active values for the same accessible fact key are rejected. Private facts belonging to another principal do not disclose their presence through a conflict error.

Invalidate → mark `invalidated`, retain reason/history and remove from ordinary recall. Historical retrieval is explicit. Delete → remove the record, FTS row and content-bearing event history; add a content-free deletion event. Deletion is logical database deletion, **not** guaranteed forensic erasure from SQLite free pages, WAL files or existing backups.

## Freshness and contradictions

Prefer current repository evidence to older/unverified observations. Context understands explicit source `Fact: key=value` declarations and flat structured configuration, plus memory `metadata.claims` objects. Disagreement is reported with evidence IDs and a preference; contradictory memories are not assembled as current facts. Source authority determines preference, with repository evidence winning equal-authority ties. Missing/changed indexed files are marked outdated and excluded from current context until reindexed.

This is not general natural-language truth detection. Use stable `fact_key` values, explicit claim metadata, references and supersession for important facts. Ordinary prose must still be reviewed by the client.

## Integrity and recovery

WAL, full synchronization, foreign keys and lock timeouts protect independent connections. Deduplication, fact conflict checks, expected revisions, state changes, FTS and events commit together. Indexing failures do not mutate this database. Health/statistics run SQLite quick checks. Online backups include committed WAL data; keep backups private and retain originals before imports. See [migration](MIGRATION.md).
