# Jev checkpoint foundation

Automatic checkpoints default off and require the explicit activation controls below. There is no new public endpoint,
MCP tool, executable tool scope, validation runner or permission grant.

## Contract and coverage

`decision_checkpoint.py` owns a versioned local envelope. Scope/policy identity,
state revision, feature provenance and checkpoint names stay local. Its Jev
projection uses only existing decision categories, booleans, phases, attempt,
revision, previous result and hard constraints. Unknown features are omitted,
never converted to false. External native/Lumi claims are agent assertions,
not trusted host observations. No raw text, path, code, output or hash is sent.

The two checkpoints are `after_inspection` and `failure_no_progress`. The first
means an inspection tool returned, not that inspection is complete or evidence
is sufficient. The second is an observed tool failure or a third identical
result. Advice never executes a retry, blocks a tool, certifies correctness or
requests owner permission merely because the provider is uncertain.

| Surface | Implemented boundary | Activation / evidence |
| --- | --- | --- |
| Native Codex | Existing `operational_guard`, operation `checkpoint` | Explicit invocation with envelope; no automatic hook claim |
| Native Pi | Tool-result extension and shared helper | New-session `checkpointsEnabled: true` or `QUATTRO_JEV_CHECKPOINTS=1`; default off |
| Qiro Codex/Pi | Host result receipt, optional instruction assembly | Exact private `jev_checkpoints_approved: true`; existing live/operational grants still required |
| Lumi | Existing `consult_task.py --checkpoint JSON` | Default preview; existing explicit `--live` grant required for a consultation |

For Codex, include `features: {}` alongside the checkpoint envelope. Pi records
actual native error flags; Qiro observes result receipts but leaves semantic
success unknown. Quattro retains provider/account/model/effort authority. Existing
strict Qiro action admission, native tool blocking and completion checks remain.
Legacy preflight recommendations retain compatibility, with `fallback_class`
separating owner authorization from agent reasoning and dependency failure.

## State, latency and evidence

New checkpoint consultations never reuse cached advice. The host tracker checks
its observed revision before and after consultation; Pi discards results after
a session/observation change. These are observed-event checks, not exhaustive
filesystem freshness guarantees. Explicit native/Lumi envelopes cannot establish
independent host freshness. Native caller observation counters map onto one
monotonic provider-session sequence so checkpoint, preflight and lifecycle
counters cannot invalidate one another; uncached checkpoints also invalidate
earlier provider advice reuse. No checkpoint advice becomes an action receipt.

The global 64-attempt ceiling is removed from `DecisionSession`; wrapper
overrides are removed. Existing single-flight admission, deadlines, cancellation,
cooldown, provider quota and strict action repetition controls remain.

Worker attempts are no longer reported as provider calls. `called=true` needs
provider-attempt/response evidence; a timeout after dispatch may remain UNKNOWN.
Checkpoint acceptance, instruction assembly, delivery, admission, receipt
consumption, observed execution and task validation are separate fields. Qiro
instruction assembly does not claim successful delivery or model reliance.
No real task benefit, provider cost or actual model reliance is inferred.

## Verification and benchmark protocol

Unit tests exercise 100 distinct consultations for native Codex, Pi helper,
Qiro Codex, Qiro Pi and Lumi. Optional `test_pi_checkpoints.py` runs 100 actual
extension callbacks with the shared helper and a synthetic evaluator; set
`QUATTRO_TEST_NATIVE_BUNDLE` to an audited local dependency bundle. It starts no
native model and makes no provider requests. Hermes contract parity is checked
when `QUATTRO_CHECKPOINT_SOURCE` points to the paired source checkout.

`python scripts/benchmark_checkpoints.py --pairs 30 --output REPORT.json`
runs five pairs each for inspection, editing, missing context, transient failure,
deterministic failure and no progress. It compares three synthetic arms:
agent fixture, same-input local rule, and Jev fixture. This checks experimental
plumbing only; fixture elapsed time is not provider RTT or task performance.

Before any approved real benchmark, freeze model/effort, source/runtime versions,
grants and task fixtures. Alternate matched arm order on fresh states. Compare
optional checkpoints off/on while keeping Qiro mandatory admission unchanged;
add a same-input local-rule arm. Judge task correctness and recommendations
independently; collect false blocks, owner requests, retries, model/tool turns,
acceptance coverage, actual provider attempts, cumulative blocking, p50/p95 task
time and cost where known. Include outages, cancellation and deterministic errors.
At least 30 matched pairs are a pilot, not statistical proof. Expand the sample
when uncertain. No live paid run or private task replay is authorized by this script.

## Integration and rollback

Apply scoped changes on the agreed integration branch; do not publish unrelated
feature-branch ancestry. Ship paired shared/host contract copies together and
reload only idle sessions. Activate only under explicit owner approval.

The deployment inventory includes `decision_checkpoint.py`, `operational_advice.py`
and `operational_native.py`. The merged-main integration carries a separate
minimal prerequisite commit for existing operational adapters and the broker
Bridge module. Apply the prerequisite and checkpoint commits together; the wider
Hermes feature-branch ancestry is not required.

Rollback restores a compatible prior code bundle and disables the optional
checkpoint flag for new sessions. It must preserve mandatory action admission;
never bypass that boundary to recover optional advice availability.

Minimum rollback floor: Quattro `7e67898452fa821af18e88b871793466b90041f1`
and Hermes `1a96ddf63a7099b741c00f054384c3b38a3b277f`. Retain their native
worker ownership, safe host repository inspection and artifact-only native
completion guards. Project validation remains pending without a separately
authorized sandboxed test route; checkpoint advice never authorizes that route.

## Approved checkpoint activation controls

Qiro reads the exact boolean `jev_checkpoints_approved` from its private host
policy when constructing the existing mandatory action advisor. Existing live
and operational approvals remain required. Native Pi reads the exact boolean
`checkpointsEnabled` from native-intelligence.json at extension load; an explicit
`QUATTRO_JEV_CHECKPOINTS=0` disables it and `=1` enables it for that process.
Both controls enable only after_inspection and failure_no_progress advice.
Reload idle sessions after changes. Native Codex/Lumi remain explicit callers.
