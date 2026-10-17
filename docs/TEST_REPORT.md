# Intelligence Core test report

Baseline verification date: 2026-10-11 UTC. Linux x86_64; Python 3.14.7, SQLite 3.53.4. The baseline did not install native agents or activate a production deployment. The separately authorized local native integration below supersedes its client-deployment limitation.

## Publication follow-through — 2026-10-17

- The owner's required branch → validate → commit → push → PR workflow is explicit in `AGENTS.md`. PR #50 publishes the accumulated standalone-core/native/reliability work; no merge into `main` or production deployment is implied.
- Fresh pre-publication Linux suite: 260 tests / one skip, OK. After reconciling current `main` and repairing native storage creation: **269 tests / three skips, OK in 30.036s**, compilation and Python hygiene pass. Two extra skips are native Windows API tests on Linux, not disabled existing coverage. The preceding isolated wheel installation, actual authorized CLI indexing/query/current citation and native-helper import passed; the temporary environment was removed.
- Initial GitHub Windows failures identified real `O_NOFOLLOW`/descriptor portability and pipe-`select` assumptions, plus POSIX-only permission assertions and noncanonical temporary repository identity. Native Windows handle traversal, actual private ACL validation and bounded queue-based stdio responses replace those assumptions. Existing protocol/isolation assertions remain. Actual Windows results are tracked on the PR, not inferred from Linux.
- Independent scoped static review found/fixed inherit-only ACL exposure of SQLite sidecars and in-place writable junction mutation. Native tests exercise broad/inherit-only ACL refusal before storage creation, sharing violations while pinned, handle release, byte bounds and current content. Windows Python 3.11 passed all configured checks at `9bce676`; Python 3.12 correctly refused the broader ACL inherited by ordinary `mkdir`. New storage/recovery directories now receive protected ACLs atomically through native `CreateDirectoryW`; existing permissions remain untouched. Static re-review cleared the creation/consumer changes. Latest-revision native qualification is tracked on the PR.
- Feature-branch integration preserves upstream desktop usage assets/docs and their changelog history while leaving the obsolete execution deployment module retired; active core has no consumers of that module.
- **Existing public-history blocker:** the full reachable-history check reports the operator-specific home path in published commit `a58015ac9f2a`, `src/restart-quickshell`. That commit is already reachable from `origin/main`. Newly introduced blob versions and the current tree passed their scans; the full-history failure remains visible. No scanner waiver, historical evidence deletion, force-push or public-history rewrite was performed to manufacture a green check.

Publication and native-platform observations above supersede the earlier dated publication/Windows limitations below; historical measurements remain preserved.


## Production reliability release — 2026-10-16

**PARTIAL acceptance, locally installed and exercised.** The three previously approved sources are reconciled; thirty other registrations require explicit scope decisions, not automatic ingestion. Publication of the accumulated unpublished rebuild history remains outside this rollout. No embedding model, vector backend, orchestration, native account, model selection or approval policy was replaced.

### Implementation and coverage

- `knowledge.py`, `config.py` and `retrieval.py`: durable intent/status/attempt/success/failure metadata, full content fingerprints, Git/secret/symlink boundaries, atomic incremental publication, bounded retry and explicit dry-run/retry/reconciliation controls. Changed/deleted/unauthorized evidence is suppressed before delivery, including failed replacement attempts.
- `native.py`, `mcp.py`, `receipts.py` and both adapters: content-free correlated lifecycle receipts with resolved project/source scope, isolated Python imports, explicit failure stages and distinct submitted/confirmed boundaries. Client acceptance and semantic correctness are not inferred from successful retrieval.
- `doctor.py`, `recovery.py`, `feedback.py` and CLI: genuinely read-only diagnosis, authorized source/result inspection, actual score contributions, principal/source-scoped diagnostic feedback, online three-store snapshots and new-directory-only recovery.
- All 33 registrations audited. Historical baseline: three successful stored snapshots, thirty never-indexed registrations, 320 files / 3,155 documents. Their initial live freshness was not established; later pre-refresh inventory is not a pristine before-change freshness baseline.
- Final deep reconciliation: **33 registered, 3 intended, 3 indexed/current, 30 pending scope decisions, 0 stale, 0 failed, 0 excluded**. The intended set is `code`, `shared-notes`, `quattro-notes`; other registrations were not treated as authorization. Evaluation artifacts are excluded from live code indexing.
- First approved refresh updated 25 code files, reconciled five removed/ineligible records and generated 682 vectors; project notes required zero updates/embeddings, shared notes one update / eleven vectors. Subsequent documentation/memory changes are incrementally reconciled after this report.
- Detailed source inventory and source-specific remediation remain private at `.quattro/reliability/source-audit-final.json`; no unrelated project roots or excerpts are published.

### Retrieval measurements

Reproducible reports: `benchmarks/reliability{,-baseline,-final}.json`. Same frozen authorized source corpus, retained vectors, memory fixtures, model, K=5 and 6,000-byte context budget; 60 source-grounded cases plus four sanitized memory-eligibility negatives. Split fixed before measurement; not independently blinded.

| Hybrid metric | Baseline | Final | Change |
|---|---:|---:|---:|
| Recall@5 | 90.38% | 90.38% | 0 pp |
| MRR | 0.8333 | 0.8333 | 0 |
| nDCG | 0.8521 | 0.8521 | 0 |
| Irrelevant knowledge-context ratio | 40.91% | 22.16% | -18.75 pp |
| Search p50 | 216.83 ms | 252.76 ms | +35.93 ms |
| Search p95 | 226.87 ms | 272.75 ms | +45.88 ms |
| No-evidence accuracy | 0/12 | 12/12 | +100 pp |

Final keyword / semantic / hybrid Recall@5: **87.50% / 88.46% / 90.38%**; search p50: **14.84 / 248.29 / 252.76 ms**; p95: **30.15 / 262.68 / 272.75 ms**. Every final strategy passed fixed isolation, freshness, memory-eligibility, availability, held-out recall and no-evidence gates. Baseline automatic context included one disputed canary per strategy; final context included none.

The measured reliability tradeoff is additional current-file authorization/fingerprint checking, not a new ranking model. Irrelevance grades knowledge units only; memory semantic relevance and exact token counts are not measured. The twelve negatives test identifiers/scope/lifecycle, not general semantic abstention. These results do not certify other projects or every natural-language question.

### Actual clients and recovery

- Native OMP and Codex each completed two automatic-context turns without tool calls, returned their newly injected random receipt identifiers and cited supplied sources. OMP's host context-message boundary was confirmed automatically. Codex stdout submission remained distinct until the exact receipt was independently observed in model output; that specific receipt was then confirmed at `codex_model_input_observed`. Runtime evidence is retained privately in `.quattro/reliability/native-delivery-proof.json`.
- Broad automatic context did not include the exact memory database filename; both clients abstained rather than inventing it. A subsequent real OMP `quattro_search_knowledge` call and real Codex MCP `search_knowledge` call retrieved current `docs/memory.md:1–3`; both answers correctly identified `memory.sqlite3` as explicit persistent memory and included the returned receipt. Codex repeated its read query once; no retry/routing change was introduced.
- Source citations and context/model-input presence were observed; this is not a universal claim that model claims are correct. Receipts keep `client_accepted` / `answer_cited` as not observed where no automatic observer exists. Direct MCP responses are not mislabeled as automatic injection.
- Actual pre-rollout online backup and isolated CLI restore included retrieval vectors/metadata, source mappings, memory history and native receipts. All three integrity checks passed; source links/checksums/schema versions were checked before recovery completion. The final recovery marker records `2026-10-16T07:06:13.529+00:00`. Live production files were never overwritten for recovery testing.
- Recovered CLI keyword retrieval returned current cited evidence with actual BM25/ranking explanations; memory history retained one event. Isolated feedback record/export retained principal and revision and did not change ranking or verification.
- Installed human-readable deep doctor returned truthful **degraded / exit 1**: all three intended sources current, databases/embeddings healthy, thirty scope decisions pending. Configuration presence, observed requests, delivery and citation observation are separate fields.
- Doctor also preserves the latest scoped confirmed-delivery observation within its last 100 host receipts separately from a newer unconfirmed request. An older delivery is not promoted to current success or semantic end-to-end verification; the behavioral regression passed.

### Validation, security and rollout

- Baseline: **222 tests, one skip**, OK. Final: **260 tests, one opt-in retained desktop skip**, OK in **30.249 s**; compilation and `scripts/check_python.py` passed. One validation command initially named a nonexistent hygiene script; corrected to the existing repository command. A relative restore path was rejected; the explicit absolute-path restore passed.
- Permanent regressions cover new/modified/moved/deleted/repeated/concurrent/interrupted indexing, failed embedding batches, wrong dimensions, bounded retries, last-known-good rollback, Git/secret/symlink boundaries, incomplete scope, actual explanation/feedback, memory authority/conflict/supersession/isolation/history, recovery tampering/scope/orphans and read-only/degraded diagnostics. Real process interruption and real hostile-cwd adapter imports are exercised.
- Six independent implementation assignments were attempted; every generic worker was rejected by its provider's weekly quota before editing. Coordinator implemented the work. The available read-only security specialist identified seven defects; each was repaired with behavioral regressions and its assigned-scope re-review passed. This is not a broad security certification.
- Built and installed the verified dependency-free final core wheel into the existing validated private venv; SHA-256 `5af280490e482e02c593a29d68610dcaea364a95cc1ac3cd5294fb25ec3d8fea`. Existing three OMP extension copies updated atomically; Codex hook/MCP registration, account credentials, native approvals and embedding service were preserved.
- Reversible package/launcher/Quattro-config/extension copies are recorded in `.quattro/reliability/rollout-backup/manifest.json`; `release-manifest.json` records their 38 file checksums, launcher restore modes and the verified thirteen-module installed-wheel closure. Persistent data is in `pre-rollout-backup`. Rollback requires quiescing Quattro invocations, restoring only those mapped artifacts/configs with executable launcher modes, or restoring data into a new verified directory and explicitly repointing configs. Never replace a live database as a recovery test.
- Coordinator/native model selection was preserved; observed OMP model was `gpt-6.1-sol`, Codex configuration remained `gpt-6.1-sol` / medium / default service tier. Worker effort selection is not exposed and remains unverified; no Fast override was requested.

Remaining release dependencies: resolve the thirty source-intent decisions before claiming organization-wide coverage; authorize publication of the existing unpublished rebuild history; broaden independently labeled project/semantic-answer evaluation before claiming universal retrieval quality. Other signed-out native profiles were not authenticated or certified.


## Native intelligence integration — 2026-10-15

- Final full suite: 222 tests, one opt-in retained desktop skip, OK in 29.212 seconds using the system interpreter with available desktop dependencies. Compilation and Python hygiene passed. Nine native-boundary regressions cover registered/shared isolation, longest-root/symlink behavior, read-only prompt context versus explicit indexing, session-bound delivery, content-free receipts, concurrent committed readers, real native MCP metadata and denied metadata-based verification authority. Two installation regressions reproduce private temporary-file exposure and wrong-store selection with a nondefault configuration, then pass after correction.
- Actual local Nomic text-v1.5 Q4_K_M, 768-dimensional learned vectors, fixed loopback endpoint. Explicit indexing generated 1,854 repository, 81 shared-note and 1,108 project-note vectors in the recorded initial passes; registered roots without an indexing pass are not claimed as covered.
- At the recorded initial validation, conceptual query `mnemonic recollections persistency` had zero scoped lexical candidates and ranked `docs/memory.md` first at cosine 0.7129096434141743. This proves a learned contribution rather than lexical feature hashing; later indexing of this report is not an independent blind rerun of that query.
- Real native omp automatically retrieved project/shared evidence in a Herdr pane, returned five evidence/memories and recorded host-confirmed context presence. A separate native standalone omp turn invoked the source-filtered `quattro_search_knowledge` tool and returned the cited memory specification and matching learned similarity. Both probes are explicitly diagnostic.
- Native Codex initialization/discovery passed after reproducing and repairing rejection of standard `clientInfo.title` and request `_meta`. Owner approved the exact new Quattro/Herdr hooks through native review; default-home trust was persisted by Codex itself. A real native turn then completed the Quattro hook with six semantic results under its actual native session ID, before the provider rejected inference for account quota. Context delivery/model reliance remain unverified; no completed Codex inference claim.
- Isolated Codex homes received the new MCP/hook configuration but their UI probes reached sign-in; they were stopped without authentication changes. Their new hook trust and model execution remain unverified until owner-controlled login/review. Existing user sessions were not closed/restarted, no credentials were copied, and native models/tool approvals/delegation were not replaced.
- Reproduced a reader startup failure while an atomic source writer held its lock; established-schema read startup now returned the prior committed fact under that same writer lock. Long indexing is outside automatic prompt hooks; missing/stale coverage is visible and mutations retain native approval.
- Historical usage receipts were inspected separately from new diagnostic receipts. Calendar-day exclusions use the operator's local timezone, not a raw UTC date prefix; zero-result completions and request-only traces are not represented as successful knowledge use.
- Independent native-security review identified two installation defects, both reproduced before and passing after: temporary copies were created under the process umask before permissions were tightened, and accepted nondefault absolute configuration roots were not propagated. Temporary files now start mode0600; the canonical discovery descriptor, client configs, MCP/hook references and global commands retain the chosen root. Repair review found no remaining actionable issue in its assigned scope. A suggested relative-path case was disproved by the existing absolute/no-traversal/no-symlink guard before writes; a subprocess probe confirmed no locator/wrapper/relative config was created. The broader core reviewer could not run because of its provider quota.
- Follow-up deadline check: cold neural indexing exceeded the former explicit native-tool bounds. Approved omp indexing and Codex MCP now allow1800seconds while automatic omp context remains20seconds. Eleven native regressions passed after the change. An actual noninteractive omp indexing attempt correctly required interactive approval and performed no mutation; a separate explicitly authorized native bridge index refreshed the registered code source. Non-retrieval receipts no longer mislabel unassessed semantics as lexical fallback or unassessed source coverage as indexed.


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
