# Hybrid retrieval and context

## Channels and fusion

`search_knowledge` operates only on active, current documents owned by configured eligible sources in the requested namespace. Optional source filters must belong to that project. `strategy` selects keyword-only, semantic-only or default hybrid with the same scope and context budget.

- **Lexical:** SQLite FTS5/BM25 over bounded query terms, omitting common natural-language glue words. Technical terms/errors remain searchable; quoted full query text receives a phrase boost.
- **Exact/code-aware:** explicit symbol/path equality and phrase matches; Python AST functions/classes/imports/top-level configuration plus generic-language symbols/preambles. Full document/code tails are split into cited chunks rather than dropped.
- **Semantic:** optional Nomic text-v1.5 learned vectors from the retained fixed-loopback local backend, model identity checked per row. Compatible vectors are searched with cosine similarity; incompatible historical vectors remain stored, not interpreted as the current model.
- **Fusion:** configurable weighted reciprocal rank `weight / (rrf_k + channel_rank)`, exact/phrase boosts, source authority/confidence and recency. Duplicate content and overlapping source spans are removed after ranking. Exact code-identifier queries require literal supporting evidence; an approximate cosine neighbor cannot justify a citation to an absent identifier.

Default lexical mode uses no embedding API and explicitly reports semantic retrieval unavailable. A stopped neural endpoint yields a query-failure reason and legitimate lexical evidence; no compatible indexed vectors is reported separately. There are no paid embedding calls, automatic downloads or fabricated semantic fallback vectors.

## Indexing

Register a root through the operator CLI; MCP accepts only its ID. Supported files are read through no-follow descriptor-relative operations. Git-backed roots honor ignore policy for tracked/untracked files; plain document roots remain usable without Git. Registration, explicit ingestion approval and successful publication are separate observations.

Each pass hashes full eligible contents, skips unchanged files, replaces changed units, removes deleted paths and treats renames as removal plus a new path. It validates the source again before atomic publication of ownership, FTS, graph/file hashes, vectors and success metadata. Attempts persist before publication; failed/interrupted replacement retains committed records and a recoverable failure marker. Transient transport/SQLite retries are bounded. Same-project root changes require explicit atomic reconciliation; source IDs cannot move projects. Force reindex only deliberately, never delete the database as a default.

Default path/credential exclusions are detailed in configuration/security docs. Explicit source roots and source IDs preserve repository-vs-note provenance even when both belong to one project. Long local-neural chunks are bounded below the backend input cap; unchanged contents are not repeatedly embedded.

## Citations and freshness

Knowledge results carry stable ID, content, symbol/type, fused/semantic scores, authority, timestamp, untrusted flag and citation: source ID/kind, namespace, relative path, line range, document/file hashes, validated current provenance and optional commit SHA. Non-current source records are suppressed rather than returned with weaker scores.

Source-file hashes, path eligibility, configured exclusions and Git policy are checked before results can be returned. Deleted, changed, excluded, inaccessible and wrong-root evidence is suppressed immediately, even before reconciliation. Non-current storage remains recoverable but is not delivered as useful current evidence. Incomplete coverage, stale suppression and semantic degradation have bounded warnings; an empty result under untested scope freshness is not proof that no answer exists.

Successful full-source validation records `INGESTION_POLICY_VERSION` in its committed summary. Only unchanged matching file hashes under the current policy can skip repeated whole-file credential rescans during interactive queries; legacy/mismatched policies still revalidate content. Path/exclusion/Git checks and hashing always remain active. Increment this version when ingestion/credential rules change; the next explicit refresh validates without reembedding unchanged files.


A commit citation is emitted only for tracked evidence indexed from a known clean Git state. Uncommitted, ignored/untracked or unknown-status evidence keeps path/line/content hashes but no invented commit reference. Incremental passes refresh commit/dirty metadata when unchanged content becomes committed, without regenerating vectors; old dirty legacy records also omit misleading commit links.

### Explanations and feedback

`query --explain` / `search_knowledge(explain=true)` expose actual BM25, keyword RRF, cosine, semantic RRF, exact/phrase boost, source-quality multiplier, final rank/score, indexed timestamp and current revision. Missing channel scores, memory verification, context selection or delivery are null when not observed. Context objects identify selected evidence; native receipts correlate those IDs/revisions with independently observed boundaries. Scores are relevance signals, not verification.

`inspect-source SOURCE [--path RELATIVE]` authorizes the configured source and current eligible file, never arbitrary roots or commands. `memory history` exposes authorized retained memory revisions. `feedback` stores only result/revision, configured principal, label and timestamp; export is principal/project scoped and does not alter ranking or verification.


## Context assembly

`get_project_context` retrieves relevant evidence and scoped active memories, prioritizes source quality/currentness and verified newer memory, removes duplication and marks evidence untrusted. Only relevant result candidates enter the context; unrelated projects and unqueryable legacy global records never enter.

The budget (512–32768, default 2000) covers the complete returned context object using a conservative UTF-8 byte upper bound. It is not an exact tokenizer estimate. Content is truncated explicitly when necessary while preserving metadata/citations; memory takes a bounded share when repository evidence exists. The enclosing JSON-RPC wrapper is outside this context budget.

Explicit `Fact: key=value` lines, flat scalar configuration and memory `metadata.claims` are compared for disagreement. Conflict markers identify preferred current evidence by configured authority, with repository sources winning equal-authority ties. Contradictory and disputed memories are excluded from automatic context; unverified memory remains explicitly unverified. Superseded/invalidated memories are preserved as historical metadata. Ordinary prose contradictions/claim entailment are not reliably detectable; clients must review evidence and citations.

## Preserved implementation and quality checks

The original real SQLite retrieval/code/benchmark implementation was retained. New service ownership prevents old global-row leakage, migrations preserve ID/vector bytes and context uses honest availability metadata. The low-level historical feature-hash backend remains for compatible storage/regression benchmarks, not as a claim of learned semantics.

Tests cover exact symbols, imports/configuration, phrases, overlapping/duplicate chunks, independent roots, changes/deletions/renames, full tails, namespace boundaries, failure rollback, provenance and memory conflicts. Real local Nomic acceptance distinguished semantic matches from a query with no lexical candidates; see [test report](TEST_REPORT.md). No universal retrieval-quality guarantee or ANN-scale throughput claim is made.

## Repeatable evaluation

`benchmarks/reliability.json` contains 60 source-grounded cases across the two previously approved namespaces plus four sanitized memory-state canaries (superseded, invalid, another principal's private memory, disputed). Source cases cover code locations, decisions, recent integration changes, debugging/recovery, cross-document questions, shared workflows and unsupported identifier/wrong-scope queries. Fixtures contain relative references, source hashes and synthetic memory IDs, not private excerpts. Other registered projects are not silently approved to broaden evaluation.

The harness calls the real scoped `KnowledgeService` for keyword, semantic and hybrid retrieval with identical K=5 / 6000-byte context budgets. Recall/nDCG credit distinct expected source files; optional symbol labels also constrain relevance. Precision and irrelevant context ratio grade knowledge units against the same file/symbol labels; memory units and ineligible-memory counts are reported separately, not graded for semantic relevance. No-evidence detection checks both selected knowledge and memory. MRR uses the first relevant rank. Search p50/p95 exclude the separately measured context request (which performs its own retrieval). Exact client-tokenizer counts are unavailable; complete UTF-8 context sizes are measured instead.

Machine reports include failures, unavailable strategies, stale results/context, boundary violations, no-evidence accuracy and case details. Comparison refuses different dataset/source/authorized-memory corpus hashes, model identity or budgets. Fixed gates require zero boundary/stale-context/ineligible-memory failures, available strategies, no failed requests, no held-out recall regression and perfect no-evidence detection on these labeled negative cases. The split is fixed, not independently blinded; binary file/symbol labels and twelve identifier/scope/lifecycle negatives do not certify general semantic answerability or correctness.

The local reproducibility artifacts are private: `.quattro/reliability/benchmark-config.json` selects the frozen baseline index; `benchmark-final-config.json` selects its policy-reconciled counterpart. Their copied eligible source files are outside index/cache-denied directories. One already-diverged, unlabeled historical routing note was excluded identically from both fixtures, as recorded in the dataset. Source fingerprints and retained vector bytes are otherwise matched; policy reconciliation of the final evaluation corpus updated/reembedded zero eligible files. Both memory stores contain the same isolated canaries; `.quattro/reliability/evaluation-memory-fixtures.json` records their IDs. These fixtures never modify live memory.

The original `bc96ae4` service plus strategy-only instrumentation is retained at `.quattro/reliability/baseline-knowledge.py`. To repeat the baseline locally without replacing the current package:

```python
import importlib.util
import json
from contextlib import closing
from pathlib import Path
from quattro_core.benchmark import evaluate_core
from quattro_core.config import Config

root = Path.cwd()
private = root / ".quattro/reliability"
spec = importlib.util.spec_from_file_location(
    "quattro_core.baseline_knowledge", private / "baseline-knowledge.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)  # Explicitly selected, trusted local baseline code.
cases = json.loads((root / "benchmarks/reliability.json").read_text())["cases"]
with closing(module.KnowledgeService(Config.load(private / "benchmark-config.json"))) as service:
    report = evaluate_core(service, cases)
(private / "baseline-rerun.json").write_text(json.dumps(report, indent=2))
```

Run Python with `PYTHONPATH=src` for the snippet. Use the command in [installation](installation.md#repeating-retrieval-measurements) and the final frozen config to repeat the gated final evaluation. Reports are measurements, not proof that an agent received, accepted or relied on any result.
