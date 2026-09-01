# Quattro Retrieval and Memory Architecture

## Purpose and authority

Quattro uses a local-first retrieval layer to select relevant evidence without
turning every prompt into a repository dump. Source code, Git, the durable task
database, and the two Markdown/Obsidian vaults remain authoritative. The private
SQLite retrieval database is a derived index and may be deleted and rebuilt.

Mandatory operational context is deliberately outside this pipeline. Compact
trusted policies from validated configuration are attached before execution and
cannot be dropped by lexical/semantic/graph ranking or context budgeting. RAG
results remain selective, bounded, and explicitly untrusted evidence.
Explicit memories added with `memory add` are the only native records whose
authority originates in the retrieval database.

## Data flow

```text
Prompt
→ deterministic query router
→ live Git/task/session state when authoritative
→ lexical FTS5 and/or local semantic feature-vector retrieval
→ reciprocal-rank fusion and metadata-aware reranking
→ bounded relationship expansion
→ content/location deduplication
→ dynamic token-budget assembly
→ untrusted-evidence envelope
→ Codex or Pi
```

The router classifies requests as no-retrieval, live state, lexical, symbol,
episodic, graph, hybrid, or multi-source before search. Exact live state,
editing-only requests, arithmetic, exact file/symbol/configuration lookups, and
continuation requests avoid semantic work. Conceptual and historical requests
use hybrid retrieval. Active repository and branch filters are applied in SQL
before ranking; current valid records exclude superseded facts by default.

## Storage

`~/.local/state/quattro/agents/private/retrieval.sqlite3` is mode `0600` in a
mode-`0700` directory. SQLite WAL and FTS5 provide local concurrency and lexical
search. Fixed-size, normalized `quattro-feature-hash-v1` vectors are stored as
binary floats. They are deterministic, require no network or model call, and
are cached by the generation-aware query cache. This is intentionally a simple
embedded vector strategy; no distributed vector service is justified for the
current single-user, local-first scale.

An explicit `local-neural` backend supports evidence-gated experiments through
a fixed loopback Nomic Embed Text v1.5 endpoint and a separate derived database.
It is never selected by default and cannot target a remote endpoint. The
real-world benchmark found only a marginal quality gain with more than twice
the query latency and materially higher indexing/RAM cost, so feature hash
remains the production backend.

Core tables:

- `documents`: code/document/memory/episode content, provenance, validity,
  importance, confidence, repository, branch, commit, symbol, and vector.
- `documents_fts`: FTS5 lexical index.
- `indexed_files`: content fingerprint and Git scope for incremental updates.
- `graph_edges`: lightweight import/call/dependency relationships.
- `query_cache`: generation/model/repository/branch-aware retrieval cache.
- `retrieval_runs`: bounded explain traces (latest 1,000).

The index generation changes after every document mutation and invalidates all
cached retrievals. Query cache retention is bounded to 100 entries.

## Memory classes

- **Working memory**: current request, recent context, live state, selected
  retrieved items, and current tool results under a token budget. It is not
  blindly persisted as long-term memory.
- **Episodic memory**: display-safe task summaries, events, and semantic
  checkpoints derived from the private harness database with task/session
  provenance.
- **Semantic knowledge**: incrementally indexed source code, configuration,
  Markdown, architecture, decisions, and project documentation.
- **Structured state**: live Git branch/commit/dirty state and authoritative
  harness task/session state. This path does not depend on vector retrieval.

## Indexing and code intelligence

Repository indexing uses only Git-tracked files when Git is available;
untracked files are excluded by default. Content hashes skip unchanged files; changed files replace their
units; missing files remove their documents and edges. Repository and branch
are part of the identity and every query scope. A different branch is never
implicitly mixed with the active branch.

Python uses the standard `ast` parser for classes, functions, imports, and call
edges. JavaScript/TypeScript, QML, Lua, and other supported text languages use
bounded symbol/import extraction. Code is chunked at symbol boundaries where
available and records path, language, symbol type, line range, hash, branch,
and commit. Exact lexical/symbol lookup runs before vector search. Graph
expansion is limited to the first three strong results and at most twelve
edges, then deduplicated and budgeted.

Launch-time indexing additionally enforces cumulative file-byte, semantic-unit,
file-count, and wall-clock budgets. Exhaustion records a bounded partial-index
status and preserves existing rows that were not safely revisited.

## Ranking and context budgeting

Candidate retrieval combines FTS5 BM25 and normalized-vector similarity using
reciprocal-rank fusion. The deterministic reranker adds source authority,
importance, recency, repository/branch scope, exact symbol matches, and
task/session affinity. Invalid/superseded records are filtered unless the query
is explicitly historical.

The context assembler reserves instruction and request space, then allocates
bounded shares to structured state, recent context, retrieval, and tool output.
It removes duplicate content and locations and truncates only retrieved data to
fit. System/developer/user instructions and exact live errors are outside this
truncation path.

## Temporal validity and consolidation

Documents support `valid_from`, `valid_until`, and `superseded_by`. Adding a new
memory with `--supersedes OLD_ID` closes the old record atomically after the new
record exists. Normal search selects current facts; `--historical` includes old
ones. Consolidation creates a bounded durable summary from recent
session/error/fix/checkpoint records and records every source ID as provenance;
raw evidence remains available. Consolidation first emits an untrusted proposal
and SHA-256; mutation requires approval of that exact proposal hash.

## Security

- Credential files, authentication directories, `.env` files, private keys,
  token patterns, and secret assignments are excluded before indexing.
- A file containing a detected secret is skipped rather than partially
  embedded. `memory add` also fails closed.
- Retrieval is scoped by repository and branch to prevent cross-project leaks.
- Task policy constrains retrieval origins. `MemoryAccess.NONE` permits
  repository evidence but excludes institutional, episodic, explicit, and
  consolidated memory.
- Retrieved code, documentation, memories, and tool evidence are always labeled
  untrusted and cannot override higher-authority instructions.
- Raw embeddings and private database payloads are not exposed in CLI
  projections. Observability stores a one-way query hash and fixed placeholder,
  never the raw query, arbitrary environments, or credentials.

Regex scanning is defense in depth, not a guarantee that every novel secret
format can be recognized. Credential stores remain deny-listed regardless of
content.

## Commands

```text
quattro-agent retrieval reindex [--directory PATH]
quattro-agent retrieval search "QUERY" [--directory PATH]
quattro-agent retrieval explain "QUERY" [--directory PATH]
quattro-agent retrieval explain                 # last trace
quattro-agent retrieval status|stats
quattro-agent retrieval eval [--directory PATH]
quattro-agent retrieval benchmark --dataset benchmarks/retrieval_real_world.json
quattro-agent retrieval open RESULT_ID [--directory PATH]

quattro-agent memory search "QUERY" [--historical]
quattro-agent memory list|stats
quattro-agent memory inspect ID
quattro-agent memory add "FACT" --type decision --importance 0.9 --confidence 1.0
quattro-agent memory add "NEW FACT" --supersedes OLD_ID
quattro-agent memory forget ID
quattro-agent memory consolidate                 # proposal only
quattro-agent memory consolidate --approve-sha256 EXACT_PROPOSAL_SHA256
quattro-agent memory reindex
```

The original `memory init`, `status`, `open`, and `open-projects` commands are
unchanged.

## Operations and migration

The first retrieval command creates the private database with an idempotent
schema. No task, session, checkpoint, or Markdown data is migrated or deleted.
`reindex` refreshes the active repository, both configured vaults, and
display-safe episodic records. Delete the derived database only when a full
rebuild is acceptable; explicit native memories should first be exported or
preserved.

Use `retrieval explain` to inspect classification, sources, filters, candidate
and selected counts, per-item score/token contribution, cache state, embedding
work, and latency. `retrieval eval` runs the representative routing/relevance
suite and reports recall-at-k, latency, retrieval token volume, embedding work,
and stale-result rate.
