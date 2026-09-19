# Quattro Intelligence

Quattro Intelligence turns existing routing and execution evidence into a
versioned, measurable ML workflow. Milestone 1 is intentionally limited to
DIRECT/DELEGATE routing. Existing deterministic routing remains authoritative.

## Architecture

```text
runtime decision ──> sanitized telemetry ──> intelligence.sqlite3
                                              │
historical TaskStore ──> extraction ──────────┤
                                              v
                                    versioned JSONL dataset
                                              │
verified labels ──────────────────────────────┤
                                              v
                                TF-IDF logistic regression
                                              │
                                              v
                                shadow prediction + benchmark
```

The authoritative harness database remains unchanged. The intelligence store is
an additive private projection under
`$QUATTRO_STATE_DIR/private/intelligence/intelligence.sqlite3`. Generated
datasets and model artifacts live beside it, not in the repository.

## Commands

```bash
quattro-agent intelligence status
quattro-agent intelligence sync
quattro-agent intelligence import-labels --input benchmarks/direct_delegate_curated_v1.json
quattro-agent intelligence dataset
quattro-agent intelligence train --activate-shadow
quattro-agent intelligence predict --prompt "Fix the parser and run tests" --repository-present
quattro-agent intelligence benchmark --pretty
quattro-agent intelligence label RECORD_ID DIRECT --source human_verified --reviewer REVIEWER_ID --notes "reviewed"
quattro-agent intelligence review-queue --production-decision DIRECT --limit 50 --output review.json
quattro-agent intelligence review-batch --input review.json --reviewer REVIEWER_ID
quattro-agent intelligence review-import --input review.json
quattro-agent intelligence review-audit --pretty
quattro-agent intelligence quality --pretty
quattro-agent intelligence phase-1-8 --output phase-1-8-report.json
quattro-agent intelligence phase-1-9 --output phase-1-9-report.json
quattro-agent intelligence blind-review-queue --reviewer REVIEWER_ID --limit 50 --output blind-review.json
quattro-agent intelligence blind-review-batch --input blind-review.json
quattro-agent intelligence blind-review-import --input blind-review.json --reviewer REVIEWER_ID
quattro-agent intelligence blind-review-audit --pretty
quattro-agent intelligence phase-1-10 --output phase-1-10-report.json
```

`sync` projects historical durable tasks into sanitized telemetry. It does not
create labels. `dataset` writes an immutable versioned JSONL dataset and a
manifest. `train` uses only independence-proven labels and fails closed until
all data-readiness gates pass. `--activate-shadow` makes the saved
model available for advisory inference; its output never changes production
routing. `benchmark` reports both the current deterministic router and the ML
model on the same held-out labels.

`phase-1-8` is non-interactive: it syncs telemetry, replaces only stale
generated probes, imports controlled probe-gold contracts, applies unanimous
Silver adjudication or exclusion, rebuilds the immutable dataset, and writes a
provenance-separated report. Historical Phase 1.8 model training now also
fails closed behind the current data-readiness gate. It never
opens a review queue, rewrites human-gold labels, activates the model, or changes
the deterministic production router.

`phase-1-9` repeats acquisition and extraction under the stricter independence
contract. It writes machine-readable JSON plus a sibling Markdown health
report, audits quarantine dispositions, and evaluates the installed shadow
artifact on independence-proven held-out evidence. Candidate training is
blocked unless every data-readiness gate passes. Any candidate remains offline;
the command verifies that the active shadow model did not change.

`phase-1-10` adds the versioned blind human-gold contract, append-only
multi-reviewer votes and correction events, agreement metrics, stratified
review sampling, deterministic semantic duplicate grouping, a fingerprinted
split manifest, and an explicit candidate gate. It writes JSON and Markdown
health reports. When any gate fails it does not train a candidate and reports
`COMPLETE — HUMAN DATA PIPELINE READY / BLOCKED BY DATA`.

The strict reviewer contract is documented in
`docs/INTELLIGENCE_HUMAN_GOLD.md`. The `blind-review-*` workflow is the only
path that can produce `blind_human_review_v2` evidence. Legacy `review-*`
artifacts remain supported for audit compatibility but are always recorded as
`legacy_exposed_review` and cannot satisfy the independent human-gold gate.

`blind-review-queue` requires `--reviewer` and `--output`. It writes a private
mode-0600 artifact with only opaque item IDs, sanitized requests, and explicit
pre-routing requirement flags. Hidden item mappings and sampling reasons remain
in SQLite. `blind-review-batch` provides resumable `DIRECT`, `DELEGATE`,
`UNCERTAIN`, and skip choices with optional reason categories and notes.
`blind-review-import` stores one immutable vote per assigned reviewer and item;
two unanimous binary reviewers are required for accepted human-gold.
`blind-review-correct` appends a superseding vote and may append a resolution
retraction. It never edits or deletes the original vote.

The older `review-*` commands remain only for historical audit compatibility.
Their imports are always `legacy_exposed_review`, do not satisfy the independent
human-gold gate, and are never upgraded by caller-supplied flags.

The one-record `label` command also requires explicit reviewer provenance for
legacy human labels and cannot relabel an excluded record. Strict blind votes
use the append-only correction workflow described above. Probe and Silver
labels are accepted only through their dedicated contract and consensus
pipelines.

## DIRECT/DELEGATE Classifier

### What

It estimates whether a request can be answered directly or should enter the
durable Codex/Pi execution path.

### Input

- sanitized request text;
- request length and estimated token count;
- request-derived repository, retrieval, tool, current-information, execution,
  modification, verification, and multi-step requirements;
- request-derived complexity, broad category, and task category.

Repository presence, source kind, entrypoint, router task type/tier, final
context size, production decisions, selected execution state, and outcomes are
excluded from the default model feature set.

### Output

`DIRECT` or `DELEGATE`, a class confidence, and the DELEGATE probability.

### Dataset

Rows come from the private runtime telemetry store and historical TaskStore
projection. Every row exposes one canonical label source: `human_gold`,
`probe_gold`, `silver`, or `excluded`, plus label confidence, labeling method,
independence status, exclusion reason, and feature provenance. Existing
human-reviewed labels are immutable. Probe labels come from explicit task contracts rather than router
predictions. Silver labels require unanimous high-confidence agreement from
three persisted, abstention-capable decision-time rubrics; uncertain cases are
excluded. Production decisions and successful outcomes are evidence, not
ground truth.

Silver is training/supporting evidence only. Human-gold real tests, probe-gold
tests, silver diagnostics, and chronological human-gold evaluation are always
reported separately. Probe and silver counts never satisfy the documented
human-reviewed-real Phase 2 gate.

Dataset manifests record the dataset schema, feature schema, content hash,
class balance, label sources, split/class counts, category and complexity
coverage, coding/non-coding balance, retrieval and tool requirements,
provider/model provenance, duplicate patterns, conflicting labels, and
real-outcome coverage. Explicit ambiguous/excluded reviews remain report-only.
Components containing conflicting verified labels are quarantined from model
training and evaluation while remaining visible in the quality audit.
Connected components link exact requests, token-Jaccard near duplicates at the
documented `0.80` threshold, deterministic concept-normalized semantic
near-duplicates at the documented `0.75` threshold, and logical-session groups before deterministic
group-stratified 70/15/15 assignment. A component is never divided across
train, validation, and test. Each v10 dataset has a separate immutable split
manifest and fingerprint; existing v10 assignments are reused and conflicting
new contamination fails closed. Controlled probe contracts use fixed split hints;
conflicting hints fail closed, and Silver components are train-only. Model features are explicitly limited to
decision-time request/profile fields; outcomes, selected provider/model,
execution tools, and timestamps remain report-only evidence.

Model-facing input is a scalar allowlist projection. Dataset rows may retain
post-decision fields for diagnostics, but those fields and their camelCase,
nested, and serialized aliases cannot enter vectorization. Text-recomputed
features are checked against a fresh reconstruction when v10 datasets load;
probe overrides require an independent non-production contract record.

### Decision-Grade Evidence Gate

`quality` and every benchmark report use independence-proven request/session
groups, not duplicated retry rows, for the Phase 2 data gate. Legacy reviews
that exposed production/output evidence remain auditable but do not satisfy
this gate. The minimum decision-grade requirements are:

- 400 independent usable groups total;
- 200 DIRECT and 200 DELEGATE groups;
- at least 30 examples of each class in validation and test;
- at least four task categories with 30 independent usable groups each;
- no broad category may exceed 60% of independent usable groups;
- zero model-input leakage or cross-split duplicate contamination;
- credible chronological independent human-gold evidence.

These are minimums for deciding whether a classical selector merits a Phase 2
experiment, not a claim of production safety. Smaller datasets remain useful
for pipeline and error-analysis work but report `BLOCKED_BY_DATA`.

Passing the data gate is necessary but not sufficient. Phase 2 additionally
requires at least 30 independent baseline/model disagreements, an exact paired
comparison at p <= 0.05 with more model wins, at least a 0.03 balanced-accuracy
improvement, no F1 regression, no worse DELEGATE false-negative rate (and at
most 0.10), expected calibration error at most 0.10, and Brier score at most
0.20. Held-out predictions and metrics must also reproduce exactly when
replayed with latency excluded. Reports include Wilson 95% intervals plus
deterministic bootstrap
intervals for calibration so small held-out slices remain visibly uncertain.
Category, complexity, class, coding/non-coding, retrieval, and tool-requirement
slices carry an explicit meaningful-sample flag.

Benchmark examples contain bounded sanitized excerpts rather than full request
text. CLI summaries never print complete review queues.

The fixed group-stratified benchmark remains the primary comparable result.
When at least 20 timestamped independent reviewed real groups exist, the report
also trains a separate model on the oldest 70% and evaluates the newest 30%.
This chronological cohort check is diagnostic and never replaces or weakens the
main readiness gates. It reports vocabulary, category, task-category, and
decision-requirement drift; legacy records do not claim a route-policy version
that was never stored.

The untouched test partition is not used for feature-set selection. Validation-
only ablations remove request text, request length, each explicit requirement,
complexity, broad category, and task category one group at a time. Reports include a
class-prior baseline, per-class false-positive/false-negative rates,
confidence distribution, abstention coverage, evidence-source and time slices,
and categorized shadow/router disagreements.

### Model

The CPU-only baseline in `src/quattro_agent/intelligence/classical.py` uses
word and bigram TF-IDF features, request-length features, leakage-safe
decision-time metadata, and binary logistic regression. Text-only and legacy
full-profile variants remain benchmark ablations. It is implemented with the Python standard library so
normal Quattro installation does not gain a heavyweight ML dependency.

### Training

Training fits the TF-IDF vocabulary and numeric scaling on the training split
only. Batch gradient descent updates one weight per feature and an intercept.
Class weights reduce majority-class bias, and connected groups contribute one
training representative. Platt calibration and the DELEGATE-risk-weighted
threshold are fit only on independent human/probe validation groups; Silver
and test rows are excluded. The model is saved as a private, versioned JSON
artifact with its dataset and feature versions. Validation metrics are reported
separately; the final benchmark remains test-only.

### Objective / Loss

Each training step minimizes weighted binary cross-entropy with L2 weight
regularization. A DELEGATE label is encoded as `1`; DIRECT is `0`.

### Metrics

- accuracy;
- precision, recall, and F1 for DELEGATE;
- confusion matrix;
- false positives and false negatives;
- confidence distribution;
- Brier score, probability reliability buckets, and expected calibration error;
- inference latency;
- disagreement rate with the current router;
- false-positive and false-negative examples;
- performance by task category and complexity when examples exist.

### Baseline

The baseline is `classify_task_request`, Quattro's current deterministic
DIRECT/DELEGATE classifier. Both baseline and ML predictions are evaluated on
the same held-out verified labels.

### Failure Modes

- Historical durable tasks are DELEGATE-biased because DIRECT responses were
  not previously persisted.
- Repeated retries and identical prompts are not independent evidence; quality
  gates and real-execution metrics collapse their connected groups.
- A successful execution does not prove delegation was the optimal choice.
- Provider failures, retrieval quality, repository state, and validation
  availability can confound outcomes.
- Sanitization reduces secret exposure but cannot prove arbitrary prose is
  non-sensitive; the intelligence store remains private.
- The tracked curated benchmark checks the pipeline but is not real production
  evidence. Production superiority remains **BLOCKED BY DATA** until reviewed
  real executions cover both classes.

### Production Status

**shadow** when an artifact is explicitly activated; otherwise **offline only**.
Inference errors are recorded as telemetry and fail open to the deterministic
production decision. Successful, failed, malformed-response, timeout, and
preflight-failed DIRECT attempts are recorded through the same private store as
durable DELEGATE tasks. ML never controls the production decision.

## Telemetry Boundary

Telemetry stores sanitized request text, hashed project/session grouping,
routing metadata, retrieval chunk IDs when available, lifecycle outcome,
validation status, retries, latency, known token usage, and known cost. Unknown
fields remain null or empty; Quattro does not fabricate them.

API keys, passwords, authorization values, cookies, credentials, private keys,
recovery codes, and arbitrary environments are never intentionally persisted.
Model output is not copied into the intelligence store.

Historical tasks that predate persisted task profiles deterministically recover
category, complexity, retrieval, and tool-requirement metadata from the stored
sanitized request. Existing execution outcomes are never used for that backfill.

## Versioning

- Intelligence database schema: `3` (blind items, votes, and resolution events are additive)
- Human review schema: `1`
- Dataset schema: `direct-delegate-dataset-v10` (v2 through v9 remain readable)
- Feature schema: `direct-delegate-features-v2` (v1 model artifacts remain readable)
- Model algorithm: `tfidf-logistic-regression-stdlib-v1`

Artifacts reject incompatible algorithm or feature versions at load time.
