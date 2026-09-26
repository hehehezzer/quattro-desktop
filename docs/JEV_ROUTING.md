# Jev as a Quattro classification signal

Default: **OFF**. No deployment or production promotion is performed by this
feature. Rebased onto latency/per-turn fix #29 at
`0f965b938e3c57a9f251103803743b8d46231981`. The Jev PR remains unmerged.

## Architecture and authority

```text
native turn / CLI prompt / harness ingestion
  -> turn_routing.extract_turn_features (one frozen predecision snapshot)
  -> deterministic DIRECT/worker gate + fast guards
  -> eligible only: bounded TypeSafe worker ----+
                   existing learned artifact --+ concurrent, optional
  -> Quattro explicit fusion policy
  -> existing capability/account/health/cost-ranked target filters
  -> one fresh locked ExecutionPlan, including immutable profile projection
  -> DIRECT transport/local handling OR validated durable-plan handoff
  -> existing OmniRoute transport and Quattro fallback supervision
```

See [UNIFIED_TURN_ROUTING.md](UNIFIED_TURN_ROUTING.md) for the entrypoint map,
invariants, review, and remaining validation gates.

There is no router-winner selection. Jev answers requirement questions. It
cannot choose an account/model, launch a worker, alter execution status, or
select a fallback. The existing DIRECT/DELEGATE and Codex/Pi gates remain hard
constraints. Existing historical evidence, local training, human-gold review,
adaptive ranking, registry eligibility, context checks, and fallback machinery
are preserved, not replaced with a second routing system.

The current registry supports approved account-qualified Codex targets, not
arbitrary models mentioned in product architecture examples. It uses configured
cost ranks among verified capable targets. This change does not invent live
pricing or historical success for those targets. Existing explicit OmniRoute
`legacy` mode remains a compatibility escape hatch; it is **not** the locked
transport architecture and is unsuitable for this experiment. Use the existing
default `passthrough` mode. No OmniRoute service/configuration is changed.

## Configuration

Merge this object into the existing `routing` group in private `ai.json`:

```json
"jev": { "mode": "SHADOW", "timeoutMs": 300 }
```

Strict accepted modes: `OFF`, `SHADOW`, `COOPERATIVE`. Timeout: integer
100–3000 ms, default 300 ms. The bearer is read only from runtime environment
`TYPESAFE_API_KEY`. Never put it in `ai.json`, shell command arguments, task
records, source, or review notes. No native Codex/Pi credential store is read.

- **OFF:** existing routing; no worker, HTTP request, Jev SQLite access, or
  extra learned inference. The existing telemetry's local shadow model remains
  unchanged.
- **SHADOW:** classification concurrent with local routing/preparation;
  never waits at the fusion boundary and cannot modify a routing requirement.
- **COOPERATIVE:** the same concurrent stage; eligible requests wait only for
  the remainder of the timeout budget. Jev failures retain the deterministic
  baseline. Conclusive/protected DIRECT, explicit models/auto aliases,
  low-complexity requirements, and already-REASONING requests do not start Jev.
  Ambiguous DIRECT may receive a capability signal but cannot become an agent. This is conservative capability fusion, not probabilistic
  worker/execution-gate replacement.

Without the key, enabled modes record `missing_credential` and normal routing
continues. Models are not guessed. Each network evaluation verifies the
approved alias through `/v1/models`; absent aliases fail open as
`model_unavailable` rather than silently switching to a different product.

## API contract and minimal input

Inspected public `https://api.typesafe.ai/openapi.json`, OpenAPI 3.1.0,
API version 0.2.0. Snapshot SHA-256:
`a191f8a7df6bd6fedced8120dd0fd106f88575d1d1c8360d08900a6c7c0360d5`.
Docs: <https://api.typesafe.ai/docs>.

Transport is direct HTTPS, fixed origin, no proxy inheritance or redirects:

1. `GET https://api.typesafe.ai/v1/models`, bearer authentication.
2. `POST https://api.typesafe.ai/v1/systemone` with `model: jev-latest`,
   `state`, and named typed `questions`.

State schema: `quattro-jev-routing-v1`. Canonical sorted compact JSON carries
only booleans and frozen categorical values. The existing decision-time
extractor supplies requirements/category/complexity; bounded lexical flags add
frontend/security/debugging/review signals. There is **no request summary or
raw text**, repository path, history, retrieved document, tool output, selected
route, prior answer, outcome, label, or credential in provider input. This
intentionally loses semantic detail; usefulness must be measured, not assumed.

Four `choice` questions: `execution`, `complexity`, `capability`, `task_type`.
Native `confidence` and per-choice `probabilities` are preserved separately.
No invented boolean probability or free-form reason is accepted. Output must
match the exact requested question/choice vocabularies, finite probabilities,
approximately normalized distributions, model identity, and bounded usage.
Unknown fields/values, duplicate JSON keys, oversized bodies, invalid JSON,
and unknown model identities fail open. The returned canonical model is
recorded separately from the requested alias and must appear in the catalog.

There are no retries. Catalog and evaluation timing are separate. The overall
child wall-clock timeout includes startup and both requests. Catalog checking
is deliberately uncached in this initial experiment; it adds observable
latency but prevents stale alias assumptions. Evaluation RTT excludes catalog,
worker startup, SQLite, and policy time.

## Explicit fusion policy: `quattro-signal-fusion-v1`

1. Preserve DIRECT/DELEGATE, worker, manual model, required capabilities, context
   eligibility, deterministic minimum quality, and deterministic tier floor.
2. Only eligible automatic non-low-complexity requests below REASONING can
   be upgraded, by **at most one tier**. This includes ambiguous DIRECT.
3. Require Jev execution to match the hard Quattro execution constraint,
   complexity=HIGH, and capability above the current floor; each relevant
   native choice confidence must be at least **0.90**.
4. An available learned DIRECT signal with confidence at least **0.80** vetoes
   an upgrade. Missing/failed local artifacts are explicit unavailable signals,
   not false zero-confidence predictions. No model is trained or activated.
5. STRONG/FRONTIER map to the existing REASONING ceiling, not an exact model
   or exceptional reasoning effort. CHEAP cannot lower deterministic requirements.
6. An upgrade is rejected unless existing Quattro registry filters admit an
   available capable target. Missing catalog/health failures retain baseline.
7. Existing exact target selection still runs downstream, using actual account,
   capability, cost-rank, context, and availability constraints. Quattro builds
   and validates the locked plan; normal fallback policy is unchanged.

The existing local safe-feature artifact is used once and its result reused by
routing telemetry, avoiding duplicate inference. Legacy unsafe artifacts remain
excluded by the existing `shadow_predict` contract. Jev never reads learned
predictions or historical labels. Signal failure cannot turn a baseline routing
error into a fabricated successful plan.

## Lifecycle and performance

`create_task` and `direct_response` own a request scope; `run_task` also owns any
nested routing work. The latency-fixed native `TurnGate.begin` transfers scope
ownership to its `Turn`, which closes it idempotently on finish, cancellation,
or session shutdown. Native sensitive/credential lookup turns skip Jev entirely.
Native DIRECT minimal context, no-tools policy, 20-second FAST budget, and locked
receipts remain intact. Already-locked plans handed to durable tasks do not
trigger another feature extraction, classification, target selection, plan build,
or Jev request. Native handoff rejects expired/already-consumed turn plans.
Each scope starts at most one worker. A process-local cap
of eight rejects excess work with a fixed-category warning. Existing Quattro
session limits remain authoritative across processes.

A non-daemon monitor owns a short-lived Python child, communicates through
anonymous pipes, enforces a wall deadline, and reaps it. The worker launches as
a small standalone module rather than importing all Quattro. It receives only
its compact state and the one provider credential over stdin. Its environment
contains only Windows system-root variables where necessary; stderr is discarded.

At scope exit, pending work is cancelled, killed, and joined, including on an
exception. Quattro does **not** wait for the provider deadline after a short
execution completes. Native turn ownership lets SHADOW overlap execution without
holding up dispatch. Cancellation is evidence, not a provider success. A
completed result is retained; shutdown persists owner-only annotations after
joining, avoiding shared task writes. Linux additionally uses parent-death
SIGKILL. Normal lifecycle is portable; abrupt-parent-death protection is
Linux-specific. An abrupt crash may leave a `pending` evidence row; it must
remain incomplete, never be counted as success.

The tradeoff is explicit: short preparation-only SHADOW scopes may cancel before
an answer arrives. Cooperative waits are bounded but not free. Joined cleanup
and private SQLite writes may add small return-path overhead; disk/scheduling
latency is not a hard real-time guarantee. This is not a persistent background
service or detached task queue.

## Evidence, provenance, and cost

Separate private `private/intelligence/jev-shadow.sqlite3`, table `jev_shadow`.
It does not alter the authoritative TaskStore or label/training tables. SQLite
busy waits are limited to 20 ms. Persistence failure skips provider spend and
emits only a constant diagnostic; other telemetry failures cannot fail execution.

Rows include observation ID, `record_id` (existing intelligence record), nullable
`source_task_id`, schema/policy versions, mode, native answers, actual model,
usage, outcome status/failure category, timeout count, agreement for analysis,
learned signal, policy constraints/reason, deterministic/final tiers, final
execution/worker/model/account/effort, and timestamps. Agreement is telemetry
only, never a policy input. Provenance is `jev_shadow_observation` in every mode;
`mode=COOPERATIVE` plus fusion reason distinguishes influence from pure shadow.
No observation is imported as a human-gold label.

Join `record_id` to `intelligence.sqlite3.routing_records.record_id` for actual
execution/validation results, execution cost, retries, fallback outcome and
actual selected target. Join `source_task_id` to TaskStore for the locked plan,
physical run, or validation lifecycle. Harness direct calls have a request record but
no durable task. Native turns instead join `turn_id`/`plan_id` to the existing
private `interactive-turns.jsonl`, preserving its metadata-only evidence boundary;
no new raw prompt/training record is created for native turns. Initial final-plan evidence is distinct from later fallback
execution evidence. Repeated requests have distinct observation IDs.

The documented TypeSafe response exposes `input_tokens` and `output_tokens`,
**not price/cost**. Jev `cost=null`, `cost_source=unavailable`; execution cost
remains in existing outcome telemetry. Total task cost must remain unknown
when Jev cost is unknown, not execution cost plus a fabricated zero. No
unverified pricing constant is introduced. Official pricing verification is
required before any estimated-cost implementation or economic promotion claim.

Timing fields: `feature_extraction_ms`, `jev_latency_ms`, `catalog_latency_ms`,
`worker_latency_ms`, `shadow_elapsed_ms`, `quattro_learned_ms`,
`deterministic_ms`, `fusion_ms`, `routing_total_ms`, and
`critical_path_wait_ms`. `dispatch_ms` is boundary-to-first direct transport,
not execution RTT; durable actual dispatch/outcomes remain in TaskStore and
execution telemetry. Hard-killed requests may have no stage-specific RTT; the
elapsed time/failure is retained rather than inventing a completed RTT.

## Validation and rollout

```bash
python -m unittest discover -s tests -p 'test_jev.py'
python scripts/benchmark_jev.py --repetitions 20
python scripts/benchmark_jev.py --native --repetitions 20
```

The benchmark uses real supervised child processes and a **simulated 20 ms
provider evaluation**, eight task types, and isolated state with no active
learned artifact. It does not contact TypeSafe. Zero fixture token counts are
not usage measurements. Full relevant suite/checks remain in `AGENTS.md`.

Live validation requires runtime `TYPESAFE_API_KEY`; unit tests never use it or
contact the service. The current session lacks that variable, so authenticated
model discovery, evaluation, native RTT, billing, and quality remain unverified.
See `JEV_BENCHMARK.md` for measured local results and limits.

Before global SHADOW -> COOPERATIVE promotion, require a separately reviewed
report after rebasing onto latency-fixed main:

- at least **400** representative paired tasks (**50 in each of eight types**),
  with at least **60 independently blind human-reviewed** tasks; no Jev-as-gold;
- **zero** hard-constraint/locked-target/worker-authority violations;
- live Jev failure and timeout rates each **<=1%**;
- added cooperative routing latency **p95 <=100 ms**, and trivial-direct added
  latency **p95 <=5 ms** versus matched OFF runs;
- task success non-inferiority: lower bound of a predeclared one-sided 95%
  paired confidence interval for cooperative-minus-baseline success **>=-2 pp**;
- verified provider pricing/usage and a reviewed success/cost comparison; no
  fabricated unknown costs, and no observed unnecessary simple-task delegation;
- independent review, full tests, and explicit rollout approval. Existing
  learned-model promotion gates are separate and remain intact.

These are release gates, not automatic runtime promotion. The configuration
supports controlled experiments now; it does not switch itself or deploy.
