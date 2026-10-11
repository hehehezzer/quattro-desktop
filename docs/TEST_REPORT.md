# Intelligence Core test report

Verification date: 2026-10-11 UTC. Linux x86_64; Python 3.14.7, SQLite 3.53.4. No hosted CI, production deployment or future agent installation is claimed.

## Executed checks

| Check | Observed result |
|---|---|
| Original full suite | 1,189 tests, 11 skipped, OK; 74.021 seconds |
| Final rebuilt full suite | 211 tests, 1 skipped, OK; 28.816 seconds |
| `compileall -q src scripts` | Success |
| `scripts/check_python.py` | PASS |
| Isolated install/build | `quattro-intelligence-core` 1.0.0 installed into repository `.venv`; no runtime Python dependencies |
| Installed distribution closure | Eight `quattro_core` modules plus standalone MCP launcher; no orchestration/desktop packages |
| Independent stdio harness | All nine tools invoked successfully; initialized without any agent executable in PATH |
| Documented plain Python client | Actual installed MCP query succeeded without an SDK/framework |
| Real repository CLI | Index, health, diagnostics and memory statistics succeeded; both databases `quick_check = ok` |
| Four concurrent first-start clients | All succeeded, same publication deduplicated to one ID, all integrity checks healthy |
| Isolated installer escape attempt | Symlinked command directory rejected; external directory untouched |
| Real legacy copy migrations | Both original retrieval stores preserved every ID/vector byte, counts and integrity; source file hashes unchanged |
| Durable archive CLI/MCP | Real CLI imports into ignored local archives; read-only archive search succeeded and indexing was denied |
| Real CLI online backup | Both current databases copied successfully to a new private destination |
| Optional learned semantic proof | Actual local llama.cpp/Nomic model indexed and retrieved conceptual evidence; temporary server stopped afterward |
| `scripts/check_public_artifacts.py` | PASS after staging intentional retirement/new files; ignored private state excluded |

The rebuilt suite retains original retrieval behavior/regressions and unchanged desktop protection while removing agent-only tests with retired functionality. Intermediate checks exposed obsolete imports, a symlink exception-contract mismatch and an invalid unscoped migration fixture; they were fixed or deliberately retired, not counted as passes. Reproduced fact-key/dedup/escaped-credential, cross-project import, unknown-schema and partial-source hazards have consumer-visible regressions. Unclosed SQLite backup/test connections were corrected; the final suite emitted no SQLite ResourceWarning.

The single skip is the opt-in retained desktop tooltip runtime check; the intelligence runtime does not require a desktop. Existing desktop fixture tests are not a claim that a new GUI was delivered or deployed.

## Acceptance scenarios

| Requirement | Executed evidence |
|---|---|
| Independent startup; no Jev/OmniRoute | Installed CLI/MCP launch from a temporary cwd with empty PATH and private HOME; core distribution closure contains no execution dependencies |
| Repository indexing | Actual configured checkout: 197 scanned, 145 updated/indexed, 52 excluded, 1,510 documents; lexical mode embedded zero |
| Accurate Git citations | Installed real-Git fixture omitted commit links for uncommitted/ignored/dirty files; committing unchanged content refreshed its correct SHA with zero updated files/embeddings |
| Exact technical/code retrieval | `persist_lesson` top symbol with path/line/hash citation; import/configuration, generic preamble and overlapping class/method regressions passed |
| Natural-language semantics | Two actual Nomic conceptual queries ranked `durable.md` first; one had zero lexical candidates |
| Hybrid fusion/deduplication | Semantic+lexical SQLite journal query ranked correct evidence first, unique IDs; duplicate-source/overlap regressions passed |
| Cited bounded context | Independent MCP context contained source citations; complete serialized context was 2,284 bytes within requested 2,400-byte budget |
| Memory survives restart | Verified memory saved, process exited, independent restarted MCP process recalled the same stable ID |
| Namespace/private isolation | Alpha memory not recalled in beta; unauthorized project/write denied; a live private record hidden from a second-principal client |
| Supersession/invalidation/deletion | New fact explicitly superseded old ID; ordinary recall returned only active successor; invalidation removed it; private record deletion succeeded |
| Changed/removed/renamed files | Actual pass: one unchanged, two updated, two deleted; new content retrieved, deleted auth document absent, renamed stylesheet citation current |
| Compatible knowledge preservation | Real migrated counts 46,440 and 2,063; ID/vector aggregate hashes match; attributed legacy-memory fixture imported unverified |
| Independent MCP contract | initialize/tools-list and all nine tools exercised by standard-library subprocess client; extra root argument rejected |
| No mandatory paid API | Default lexical operation used no API; learned embeddings used existing local model/binary, no cloud request/model download |
| Index failure integrity | After stopping local server, forced neural reindex raised real URLError; prior document/hash aggregate unchanged; both databases healthy, failed attempt explicitly reported |
| Sensitive/excluded files | `.env` and dependency sentinel absent from search; credential/private-key/escaped-string and exclusion regressions passed |
| Unknown database protection | Reproduced unsafe acceptance before fix; final standalone smoke rejected unrelated schema with original file SHA-256 unchanged |

The real repository indexing counts above are the measured initial acceptance corpus, not a promise that counts stay fixed after this report/notes/commits are added.

## Representative retrieval comparison

Same three project queries, limit five. Original temporary corpus: 3,447 documents with feature-hash retrieval. Rebuilt acceptance corpus: 1,510 documents with namespace-scoped lexical/code-aware retrieval. Latencies are single in-process observations including provenance checks, not a statistically controlled benchmark; the corpus changed substantially when execution source was retired.

| Query / expected symbol | Original rank | Rebuilt rank | Original ms | Rebuilt ms |
|---|---:|---:|---:|---:|
| `QueryRouter` | 1 | 1 | 76.80 | 13.99 |
| `LocalNeuralEmbeddingBackend` | 2 | 1 | 73.51 | 7.49 |
| `retrieved content untrusted evidence` → `ContextAssembler` | absent in top 5 | 4 | 78.82 | 10.96 |

Actual learned model: Nomic text-v1.5 Q4_K_M, 768-dimensional vectors through the retained fixed loopback backend. Three changed fixture files embedded; unchanged reindex embedded zero. Conceptual query results:

| Query | Top evidence | Cosine similarity |
|---|---|---:|
| How can I remember lessons tomorrow after shutting the program down? | `durable.md` | 0.652546 |
| How will I retain discoveries for tomorrow when my application is no longer running? | `durable.md` | 0.626731 |

The second query returned zero candidates in lexical-only mode. This proves exercised local semantic capability for the representative fixture, not universal semantic quality. After server shutdown, lexical results still worked and returned explicit semantic unavailability.

## Known limits and intentional exclusions

- Default lexical mode is fully standalone. The optional learned backend needs a separately operated compatible local server; it is not left running or silently provisioned.
- Context budgets are conservative UTF-8-byte upper bounds, not exact model-tokenizer budgets; JSON-RPC wrapper overhead is outside the context object budget.
- Contradictions are detected for explicit fact declarations/flat scalar configuration/recorded claims and supersession, not arbitrary natural-language prose.
- Source-pass bounds: 20,000 scanned files, 512,000 bytes per file, 64 MiB total content, 500 units per file and 5,000 units per pass. Use narrower configured roots/exclusions for large sources; bound violations roll back rather than silently returning partial coverage.
- Cosine vector ranking is local SQLite-backed scanning, not an ANN-scale throughput claim. No PostgreSQL/pgvector or HTTP API was implemented; neither is required for the delivered independent service.
- Config/principal enforcement is application-level, not an OS sandbox for a client that can replace config or read databases directly. Credential patterns cannot recognize all sensitive prose; logical deletion cannot erase prior backups.
- Ambiguous/global/other-project legacy records and execution/routing telemetry are preserved but not auto-promoted to active factual memory. Migration report provides exact assignment/quarantine counts.
- Windows portable CI is configured but not locally executed; Windows indexing/macOS runtime and hosted CI are unverified.
- Installed historical desktop/agent integrations and live legacy databases were intentionally not changed. No production activation, external publication or future framework installation occurred.
