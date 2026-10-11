# Hybrid retrieval and context

## Channels and fusion

`search_knowledge` operates only on active documents owned by explicitly configured sources in the requested namespace. Optional source filters must belong to that project.

- **Lexical:** SQLite FTS5/BM25 over bounded query terms, omitting common natural-language glue words. Technical terms/errors remain searchable; quoted full query text receives a phrase boost.
- **Exact/code-aware:** explicit symbol/path equality and phrase matches; Python AST functions/classes/imports/top-level configuration plus generic-language symbols/preambles. Full document/code tails are split into cited chunks rather than dropped.
- **Semantic:** optional Nomic text-v1.5 learned vectors from the retained fixed-loopback local backend, model identity checked per row. Compatible vectors are searched with cosine similarity; incompatible historical vectors remain stored, not interpreted as the current model.
- **Fusion:** configurable weighted reciprocal rank `weight / (rrf_k + channel_rank)`, exact/phrase boosts, source authority/confidence and recency. Current provenance receives priority over changed/missing evidence. Duplicate content across sources and overlapping source line spans are removed after ranking.

Default `embedding: lexical` uses no embedding API and returns `semantic.available: false`, reason `lexical-only`. A configured but stopped neural endpoint returns an explicit query-failure reason and useful lexical results. An operational endpoint with no compatible indexed vectors reports that distinction. There are no paid API calls, automatic downloads or fabricated semantic fallback vectors.

## Indexing

Register a root once through the local CLI; MCP accepts only its ID. Supported repository/text/Markdown/structured files are read through no-follow descriptor-relative operations. This scans supported files under configured roots, including untracked files unless excluded. Git is optional commit/dirty provenance, not an execution framework.

Each source pass hashes full contents, skips unchanged files, replaces changed units, removes deleted paths and treats a rename as removal plus a new path. The complete source replacement commits atomically, including ownership, FTS, graph/file hashes and vectors. Failed traversal/read/embedding/storage retains the last committed index and records failure status. Forced reindex regenerates authorized source units; never delete the whole database to reindex.

Default path/credential exclusions are detailed in configuration/security docs. Explicit source roots and source IDs preserve repository-vs-note provenance even when both belong to one project. Long local-neural chunks are bounded below the backend input cap; unchanged contents are not repeatedly embedded.

## Citations and freshness

Knowledge results carry stable ID, content, symbol/type, fused/semantic scores, authority, timestamp, untrusted flag and citation: source ID/kind, namespace, relative path, start/end line, document hash, full-file hash, current/outdated/missing provenance and optional commit SHA.

Source-file hashes are checked at query time using safe opens; status is cached per source/path/hash for that query. Search can surface outdated evidence with explicit provenance. Context does not present missing/changed files as current facts; reindex after edits. Citations allow clients to locate and independently inspect the evidence, not execute it.

A commit citation is emitted only for tracked evidence indexed from a known clean Git state. Uncommitted, ignored/untracked or unknown-status evidence keeps path/line/content hashes but no invented commit reference. Incremental passes refresh commit/dirty metadata when unchanged content becomes committed, without regenerating vectors; old dirty legacy records also omit misleading commit links.

## Context assembly

`get_project_context` retrieves relevant evidence and scoped active memories, prioritizes source quality/currentness and verified newer memory, removes duplication and marks evidence untrusted. Only relevant result candidates enter the context; unrelated projects and unqueryable legacy global records never enter.

The budget (512–32768, default 2000) covers the complete returned context object using a conservative UTF-8 byte upper bound. It is not an exact tokenizer estimate. Content is truncated explicitly when necessary while preserving metadata/citations; memory takes a bounded share when repository evidence exists. The enclosing JSON-RPC wrapper is outside this context budget.

Explicit `Fact: key=value` lines, flat scalar JSON configuration and memory `metadata.claims` are compared for disagreement. The result includes evidence IDs and preferred current evidence based on configured authority, with repository sources winning equal-authority ties. Contradictory memory is excluded even if conflict details cannot fit. Superseded/invalidated memories and changed/missing source evidence can be annotated as outdated. Ordinary prose contradictions are not reliably detectable; clients must still review evidence.

## Preserved implementation and quality checks

The original real SQLite retrieval/code/benchmark implementation was retained. New service ownership prevents old global-row leakage, migrations preserve ID/vector bytes and context uses honest availability metadata. The low-level historical feature-hash backend remains for compatible storage/regression benchmarks, not as a claim of learned semantics.

Tests cover exact symbols, imports/configuration, phrases, overlapping/duplicate chunks, independent roots, changes/deletions/renames, full tails, namespace boundaries, failure rollback, provenance and memory conflicts. Real local Nomic acceptance distinguished semantic matches from a query with no lexical candidates; see [test report](TEST_REPORT.md). No universal retrieval-quality guarantee or ANN-scale throughput claim is made.
