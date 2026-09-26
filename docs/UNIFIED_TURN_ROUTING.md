# Canonical per-turn routing

Status: implementation validated locally; **not merged, deployed, or promoted**.
Base: main `0f965b938e3c57a9f251103803743b8d46231981` (PR #29).
Delivery: PR #30, `feat/jev-shadow-routing`. Default and inspected runtime
configuration: **OFF** (no explicit Jev override). No credential configuration
was changed.

## One authoritative pipeline

```text
native Codex/Pi turn          CLI prompt / harness task or direct request
          \                           /
           extract_turn_features once
             frozen TurnRoutingFeatures
               /                    \
        local projection       bounded Jev projection
               \                    /
       deterministic execution/worker constraint + fast guards
       eligible: optional local learned and Jev work overlap
                     Quattro fusion
          capability/account/health/cost/context filters
               one fresh immutable ExecutionPlan
                    /               \
       DIRECT/local handling    consume validated plan
       no task/agent loop       one durable worker dispatch
                    \               /
              locked OmniRoute transport
```

`src/quattro_agent/turn_routing.py` owns extraction, eligibility, evaluation,
fusion invocation, exact-target selection, and initial plan construction.
`TurnRoutingFeatures` stores immutable JSON projections plus the existing
frozen deterministic gate result. Existing feature, task-profile, and lexical
gate extractors each run once inside that stage; this is one canonical snapshot,
not a claim that all legacy lexical rules were replaced with one regex pass.
No new learned model, training, labels, or activation are introduced.

Entrypoints:

- `TurnGate.begin`: invokes the canonical pipeline; owns optional work until
  finish/cancel/shutdown. Native Codex and Pi retain their actual TUIs.
- `cli.run_prompt`: extracts once to choose direct versus durable handling,
  then passes the same immutable features into the harness.
- `HarnessRuntime.create_task`, `_pre_route`, and `direct_response`: consume
  those features or extract once when called independently.
- A supplied native plan is validated against current account, target, health,
  capability, and context constraints, then consumed. Its saved profile (or a
  legacy contract projection) replaces text reclassification. It does not
  select another target, construct another initial plan, or emit another routing
  decision record.
- `native_session.delegate` checks the active plan identity and single-use task
  assignment under its lock. Finished/expired and already-consumed plans cannot
  create another native task. `TurnGate.begin` always allocates a fresh plan;
  resume restores bounded conversation, not an old routing decision.
- Explicit already-created Pi/review subtasks retain their bounded worker
  lifecycle. Explicit legacy OmniRoute routing remains compatibility-only,
  outside the supported locked passthrough pipeline.

Successful turns create **one initial plan**. Provider fallback plans are
materialized lazily only after an eligible execution failure, from Quattro's
already-approved candidates; they are not another classifier invocation.
Same-target transport retries reuse that attempt's plan. Native DIRECT still
has no fallback; noninteractive direct transport retains its existing controlled
provider-failure fallback, minimal context, and empty tool requirements.

## Authority, eligibility, and privacy

Conclusive DIRECT, credential/redacted requests, manual models/aliases,
LOW-complexity requirements, and deterministic REASONING ceilings do not start
Jev. Trivial native DIRECT also skips learned inference, retrieval, task creation,
worker selection, and the agent loop. Credential requests return the existing
local safe explanation without searching credential stores or forwarding the
request to a model. This is handling, not a credential retrieval implementation.

On eligible requests the supervised Jev child starts before local prediction;
Quattro uses explicit conservative fusion, never an average. An ambiguous
DIRECT can receive a capability uplift without becoming DELEGATE. The existing
execution/worker gate, deterministic floors, explicit targets, registry
capabilities, enabled accounts, health exclusions, context capacity, and cost
ranking remain authoritative. Disabled accounts are never resurrected by the
preferred-account default. Explicit targets cannot bypass health exclusions.
Native turns reuse the bounded, read-only existing account-health snapshot.

OFF starts no Jev work and adds no native learned inference. Existing harness
telemetry can still evaluate its existing safe artifact, using the already
computed local projection. SHADOW does not affect selection. COOPERATIVE waits
only its remaining bounded routing budget and can raise an eligible capability
floor by at most one tier. Missing models, credentials, timeouts, malformed
responses and telemetry failures are optional-signal failures, not replacement
policy. See [JEV_ROUTING.md](JEV_ROUTING.md) for precise thresholds and API schema.

No persistent daemon/client was introduced. Fast guards remove process startup
from trivial turns; a killable supervised subprocess still supplies reliable
DNS/network cancellation for eligible turns. It is lifecycle-owned, joined and
reaped, not detached. Catalog/evaluation overhead remains measurable and is not
hidden behind a claimed 20 ms provider RTT.

## Correlated private telemetry

Native `interactive-turns.jsonl` records plan/turn/session/task IDs, guard,
feature extraction and target-selection timing, learned evidence, fusion reason,
final target/effort, dispatch/model counts, outcome/lifecycle state, and the final
Jev observation when requested. There are planned and terminal lifecycle events,
not two competing decisions. A missing component is unavailable, not zero cost
or invented success. Native rows do not contain prompt/history text or the
feature projection's local request text.

Jev's private SQLite observation remains auxiliary evidence, joined by
`plan_id`/`turn_id`, or harness `record_id`/`source_task_id`. It is not a second
routing authority, human-gold label, or training outcome. Harness/native execution
and validation outcomes stay in their existing stores. Costs remain null until
verified; the documented TypeSafe response supplies usage but not billing.

## Regression evidence

Local final validation: **685 tests, 5 platform skips**, including 37 Jev tests
and 14 new unified invariants. Compileall, Python hygiene, public-artifact
policy and whitespace checks passed.

Instrumented hermetic cases assert:

| Case | Canonical extraction | Initial plan build | Jev calls | Task / agent lifecycle |
|---|---:|---:|---:|---|
| Trivial native DIRECT, all modes/frontends | 1 | 1 | 0 | bypassed |
| Protected local DIRECT | 1 | 1 | 0 | bypassed; no model dispatch |
| Eligible delegated native turn | 1 | 1 | at most 1 | one validated handoff |
| Harness receives supplied native plan | 0 | 0 | 0 | consumes same plan |
| CLI features handed to harness | 0 additional | 1 | eligibility-dependent | no second extraction |
| Repeated/expired native handoff | 0 additional | 0 | 0 | rejected |

The sequence DIRECT → DELEGATE → DIRECT has three different plan IDs, no stale
plan lookup, and lifecycle flags false → true → false. Resume-history import,
immutable projections, no learned re-extraction, local credential handling,
health exclusions, disabled accounts, minimal direct fallback semantics, and
no eager fallback-plan build are tested. Existing transport/bridge tests exercise
real local HTTP/process supervision, cancellation and locked receipts; these are
not paid external-provider smoke tests.

Independent read-only Codex review found an OFF-mode inference regression; it
was fixed and covered by a regression test. The follow-up architecture/lifecycle
review and final native-handoff/guard review reported **no substantive findings**.
The first broad reviewer timed out without a final report and is not counted as
approval. Supplied plans remain a trusted internal Python API, not an untrusted
external plan-submission endpoint; the native handoff additionally enforces
active identity and single consumption.

## Current hermetic benchmark

Python 3.14/Linux, 20 repetitions × 12 categories × 3 modes × 2 entrypoints =
**1,440 routing measurements**. Commands:

```sh
python scripts/benchmark_jev.py --native --repetitions 20
python scripts/benchmark_jev.py --repetitions 20
```

Real supervised child, simulated 20 ms evaluation, simulated zero catalog
latency, real features/fusion/registry/SQLite. An 80 ms simulated execution
interval is excluded from routing latency. No active learned artifact in the
isolated store: its timing is an unavailable-artifact check, **not inference**.
The harness measurement is the canonical routing boundary, not full harness
startup, context loading, dispatch, or response time.

| Entry | Mode | n | p50 ms | p95 ms |
|---|---|---:|---:|---:|
| Native | OFF | 240 | 0.586 | 0.785 |
| Native | SHADOW | 240 | 0.626 | 0.828 |
| Native | COOPERATIVE | 240 | 0.669 | 61.182 |
| Canonical harness boundary | OFF | 240 | 0.476 | 0.598 |
| Canonical harness boundary | SHADOW | 240 | 0.490 | 0.682 |
| Canonical harness boundary | COOPERATIVE | 240 | 0.496 | 61.170 |

Native per-category p50 / p95 ms, n=20 per cell:

| Category | OFF | SHADOW | COOPERATIVE |
|---|---:|---:|---:|
| Trivial informational | 0.594 / 0.741 | 0.578 / 0.697 | 0.610 / 0.713 |
| Ambiguous wording | 0.699 / 0.877 | 0.698 / 0.886 | 0.692 / 0.831 |
| Repository concept question | 0.589 / 0.711 | 0.595 / 0.742 | 0.625 / 0.751 |
| Credential lookup | 0.644 / 0.767 | 0.612 / 0.717 | 0.680 / 0.824 |
| Traceback/resume-shaped prompt | 0.580 / 1.079 | 0.585 / 0.671 | 0.601 / 0.738 |
| Coding question | 0.631 / 0.785 | 0.616 / 0.746 | 0.631 / 0.735 |
| Repository modification | 0.486 / 0.596 | 0.690 / 1.111 | 58.646 / 61.509 |
| Frontend implementation | 0.549 / 0.729 | 0.719 / 0.833 | 58.620 / 61.309 |
| Debugging | 0.540 / 0.658 | 0.710 / 0.868 | 57.407 / 61.825 |
| Research | 0.658 / 0.787 | 0.584 / 0.665 | 0.635 / 0.762 |
| Complex coding | 0.546 / 0.673 | 0.532 / 0.702 | 0.560 / 0.672 |
| Review | 0.552 / 0.686 | 0.559 / 0.677 | 0.573 / 0.686 |

The "resume" benchmark is routing-only prompt shape; actual bounded history
restore is covered separately by tests. The ambiguous fixture has conclusive
requirements and skips Jev; a separate test covers an eligible ambiguous DIRECT
and a schema-valid capability uplift. Do not imply every ambiguous phrase needs
remote classification.

Only **60/240** turns request Jev in each enabled mode/entrypoint; **180/240**
skip it. OFF requests zero. Simulated failure/timeout counts are 0/60 and
agreement is 60/60; none are live quality evidence. OFF and SHADOW select
Luna/Terra/Sol 120/80/40; COOPERATIVE selects 120/60/60, through Quattro policy.
Native COOPERATIVE eligible-component p50/p95 (n=60): feature extraction
0.277/0.360 ms; artifact-unavailable check 0.023/0.040 ms; simulated evaluation
20.090/20.100 ms; fusion 0.009/0.074 ms; explicit wait 56.875/60.762 ms.
Parallel components must not be summed. Startup/catalog/lifecycle overhead is
not provider RTT. No first-token/paid-model/actual-tool/cost timing is claimed.

### Direct comparison against main #29

An untouched `git archive` of main #29 was extracted into `/tmp`, not another
session's worktree. The identical no-network `TurnGate.begin/finish` probe ran
against each source tree: five warmups + 20 measured repetitions per category.
Both used default OFF, no active artifact and temporary state. These warm
routing-only observations differ from the above paced simulated-execution run.

| Case | Main #29 p50/p95 ms | Canonical p50/p95 ms |
|---|---:|---:|
| TUI definition | 0.213 / 0.229 | 0.360 / 0.447 |
| API gateway definition | 0.241 / 0.370 | 0.364 / 0.396 |
| Credential question | 0.221 / 0.235 | 0.383 / 0.433 |
| Traceback explanation | 0.176 / 0.221 | 0.325 / 0.415 |
| Repository modification | 0.111 / 0.153 | 0.344 / 0.452 |
| Frontend implementation | 0.117 / 0.143 | 0.268 / 0.392 |

Canonical metadata/projection work costs measurable fractions of a millisecond;
this is **not a speedup over #29**. The sampled trivial DIRECT p95 increase is
0.218 ms or less, below the predeclared 5 ms bound. It still never pays Jev
startup/wait or an agent lifecycle. This local sample is not production p95.
Historical pre-unification results remain in [JEV_BENCHMARK.md](JEV_BENCHMARK.md).

## Release gates and limitations

**LIVE JEV VALIDATION: BLOCKED — TYPESAFE_API_KEY unavailable.** Authenticated
catalog/canonical identity, live inference, network latency, pricing, billing,
quality and human-reviewed promotion evidence remain unverified. No production
SHADOW/COOPERATIVE promotion is justified by simulated fixtures.

No canonical-pipeline merge or installation was performed. A subsequent narrow
installed `native_session.py` hotfix addresses Codex's remote `--add-dir`
rejection without installing Jev/unification; see `interactive-routing.md`.
The primary checkout remains at #29;
live native-provider behavior has not been validated by this change. A later
launcher investigation confirmed that installed modules live beside the script
under `~/.local/bin/quattro_agent`; a `python -c` import probe from `/tmp` omits
that script directory and is not a valid installed-launcher health check.
Linux/Windows hosted CI for the new revision must be checked on the PR before
integration. Canonical-pipeline deployment and real native-provider smoke remain
gated; services, configuration and other session worktrees were not modified.
The narrow launcher hotfix is backed up locally and is not a full manifest release.
