# Original-system audit and baseline

## Discovery and safety

The actual checkout was `quattro-desktop`, branch `feat/dynamic-main-integration`, clean at `dc88f61d84c0765078a2292823abfca29a39e533`. Rebuild branch: `feat/intelligence-core-rebuild`. A complete Git bundle was verified before source retirement. SQLite online backups of six actual databases all returned `quick_check = ok`; durable private copies are outside this repository. Exact private filesystem locations are deliberately omitted from publishable documentation and reported to the operator separately.

The shared Obsidian index, project-note index, Quattro project architecture/notes and shared security/workflow instructions were inspected. Code and notes live in independent roots. No entire vault, example unrelated repository or unconfigured home tree was indexed.

## Original product

The dependency-free Python distribution `quattro-agent` v0.2.0 combined a durable execution harness, provider/account/model routing, Jev decisions, OmniRoute transport integration, native Codex/Pi/OMP execution/lifecycle hooks, agent workers, deployment controls, sessions and desktop projections with optional retrieval. Its initializer eagerly imported execution code.

`shared_intelligence.py` described itself as client-neutral but imported native intelligence, DecisionSession, Jev and supervisor modules. `quattro_intelligence_mcp.py` mixed retrieval with operational guards, decisions and RTK execution. The Pi intelligence adapter hooked retrieval into native-client lifecycle. These were not independent intelligence-only contracts; their execution consumers had to be retired rather than silently reused.

`src/quattro_agent/retrieval.py` already provided WAL/FTS5/BM25, reciprocal-rank fusion, feature-hash vectors, fixed-loopback local Nomic embeddings, code AST units/import/call edges, hashes, provenance, source ranking, deduplication and context assembly. `benchmark.py` and retrieval tests were reusable. These implementations were moved and modernized, not discarded for an easier replacement.

Observed hazards: index-generation mismatch deleted derived rows; source replacement committed units separately; global rows could enter repository queries; some imports pulled in execution eagerly. New ownership/transaction/migration boundaries address these hazards.

## Actual storage/model inventory

| Store | Original schema / observed contents | Disposition |
|---|---|---|
| `retrieval.sqlite3` | Index v2; feature-hash 256; 46,440 documents, 8,788 files, 99,255 edges | Backed up; real-copy preservation migration verified |
| `retrieval-neural.sqlite3` | Index v2; local Nomic 768; 2,063 documents, 105 files, 3,478 edges | Backed up; real-copy preservation migration verified |
| `harness.sqlite3` | Schema 4; tasks/events/checkpoints and execution state | Historical backup only |
| `native-intelligence.sqlite3` | Native telemetry | Historical backup only |
| `native-intelligence-pre-live.sqlite3` | Pre-live telemetry | Historical backup only |
| Nested `intelligence.sqlite3` | Routing-research schema 4; 1,109 routing records | Backed up as `intelligence-routing.sqlite3`; retired from runtime |

No document/credential dumps were produced. The feature-hash store spanned 361 repository identities and 59 global rows; this required explicit mapping/quarantine instead of assigning every row to one new project. Neither retrieval store contained compatible explicit/approved memory rows to auto-promote.

Existing local llama.cpp and quantized Nomic weights were found and reused for optional semantic acceptance. The fixed loopback endpoint was unavailable at initial audit. Temporary local servers were started only for proof and stopped afterward; the default new service remains lexical and independently operational.

## Executed baseline

Original full suite: `python -m unittest discover -s tests -p 'test_*.py'`: **1,189 tests, 11 skipped, success in 74.021 seconds**. An existing unclosed SQLite ResourceWarning was observed.

A temporary index of the original repository scanned 432 files, indexed 359, excluded 73 and stored 3,447 documents. Query limit five, feature-hash backend:

| Query | Expected symbol | Original rank | Original latency ms |
|---|---|---:|---:|
| `QueryRouter` | `QueryRouter` | 1 | 76.80 |
| `LocalNeuralEmbeddingBackend` | `LocalNeuralEmbeddingBackend` | 2 | 73.51 |
| `retrieved content untrusted evidence` | `ContextAssembler` | not in top 5 | 78.82 |

Feature hashing is lexical similarity/alias expansion, not learned conceptual matching. The new default does not pretend otherwise. Rebuilt measurements and actual local neural proof are in [test report](TEST_REPORT.md).

## Consumer retirement decision

New package/installers export only intelligence CLI/MCP. Legacy native registration, execution adapters/entrypoints and orchestration tests/benchmarks are retired from active source. General desktop source/assets/helpers are frozen and excluded from the wheel. No installed desktop, external agent, Jev, OmniRoute, protected native session or global client configuration was modified or restarted. See [migration](MIGRATION.md) for incompatible data and rollback.
