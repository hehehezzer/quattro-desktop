# PR #31: host runtime milestone experiment

Continuation of exact `766c391d257a3eea29a5191c2c8ba2642e5c5fe3`.
This is **not completion of the session-wide offloading objective**. No default
automatic category is enabled. Do not merge or deploy on this evidence alone.
The existing architecture and [callable advice](JEV_DECISION_PLANE.md) remain.

## Actual event/control audit

| Runtime path | Observed event | Existing host control | Treatment |
|---|---|---|---|
| Native Codex `CodexTurnBridge._backend_reader` | `item/started`, `item/completed` for command execution, file changes, MCP/dynamic tools, search | Forward notifications, invalidate advice | Observation is **not** permission to execute or replace a native tool |
| Native Codex | `turn/completed`, agent message, interrupt | Finish/remember/cancel turn; lock initial dispatch | No synthetic tool responses or unauthorized commands introduced |
| Managed Codex | JSONL output, supervised process exit, locked receipt | Durable completion and required validation | Shared validation milestone below |
| Routed Pi UI | Input, cancel, shutdown, blocked native tool calls | `/turn` gate delegates to **Codex** | Not standalone Pi proof |
| Standalone managed Pi | `PiAdapter` child exit, locked receipt, artifact | Same `HarnessRuntime.run_task` and `validate_task` as Codex | Shared validation milestone; actual Pi live probe included |
| Pi JSON worker | Message/tool events available in native JSON output | Existing bounded output collector, no bidirectional execution gate | No invented tool interception claim |
| Managed failures/retries | Child failure, terminal gateway receipt, task transition | Deterministic retry limits/backoff and locked fallback plans | Not delegated to Jev; no authority changes |
| Skills, repository semantics, root cause | Agent-owned internal choices/tool arguments | No common mid-turn action dispatcher | `AGENT_REASONING`; remain callable where already supported |

The shared executable flow is:

```text
CodexAdapter or PiAdapter
  -> supervised real child execution
  -> successful exit + existing locked receipt/artifact checks
  -> VALIDATING_RESULT
  -> host constructs existing mandatory validator closures
  -> host.validation.ready
  -> cheap eligibility + explicit experiment gate
  -> existing DecisionSession + existing validation_strategy taxonomy
  -> valid, confident and still-current ordering?
       no: existing check order
       yes: host permutes the same closures
  -> run every required check once
  -> existing aggregate validation and task lifecycle
```

No execution model is asked to call Jev. No decision is appended to model
context. No command, path, source, output or transcript goes to Jev. Neither a
provider answer nor an eligible milestone grants capabilities. The host still
owns validators, argument vectors, policy, timeouts, receipts and success.

## Conservative scope and gating

`routing.jev.experimentalValidationOrder: true` is an **opt-in experiment**, not
a production recommendation. It also requires `mode: COOPERATIVE`. Missing,
false, OFF or SHADOW never starts a milestone worker. Only a plan with both
focused checks and a broad suite, 2–16 checks total, can qualify. All other
milestones go to normal execution/agent reasoning immediately.

The candidate can reorder Git diff integrity and the already selected language
suite. Read-only-policy guards are pinned before any reordered suite: a suite
must not hide an agent violation by repairing the tree before that guard runs.
Unchanged/fallback plans retain their original order. The candidate cannot add,
omit, parallelize or retry validators.
The action vocabulary remains `targeted_first`, `broad_first`, `agent`; focused
checks are not misrepresented as focused semantic tests. Every mandatory check
still runs. Provider uncertainty retains the original order. The request uses
only categorical constraints and two host-observed validation flags.

A successful changed order is recorded `OFFLOADED` **only at real check
dispatch**. An unchanged order is `FALLBACK/unchanged_order`, not a claimed win.
Uncalled, disabled or ineligible observations are `PASSTHROUGH`, not counted as
provider fallbacks. Callable MCP answers separately carry `ADVISORY` or
`FALLBACK`. Critically, the
validation candidate records `agent_reasoning_avoided: false` and
`model_turns_avoided: 0`: the baseline already ordered host checks deterministically.
Reordering is not evidence of useful reasoning offload or Jev speedup.

Each validation scope owns one existing bounded DecisionSession. No queue or
additional provider/executor architecture is introduced. Its call ceiling is
750 ms (or the configured smaller timeout); ineligible/default paths do not
start workers. State is checked during the bounded provider wait, after advice and before
dispatch. State lookup runs on the existing monitor, not the caller: even a
stalled database read cannot extend the decision caller's deadline. A
cancellation predicate signals non-joining session shutdown instead
of waiting for the provider deadline. If a task leaves validation while the
experiment is active, no subsequent check starts; `run_task` preserves
cancellation rather than declaring success. Cancelling a validating task whose
native run already succeeded never signals the reaped child's PID or tries to
transition that succeeded run back to interrupted. It remains `CANCELLING`
until the owner exits its wait or completes its bounded active validator; it
must not report terminal cancellation while that check is still executing.
Manual and workflow-parent validation (without a native run identity) never
starts the experimental decision worker. The existing
monitor retains termination/reaping/capacity ownership. `request_close()` avoids
joining cleanup on the validation dispatch path. Active validator subprocesses
retain their existing bounded-command behavior; no stronger preemption claim is
made.

## Latency attribution, not aggregate hiding

The previous single runtime call had:

- blocking wait: **637.289 ms**;
- Jev evaluation RTT: **282.724 ms**;
- catalog fetch: **312.822 ms**;
- remainder (startup, IPC, scheduling and validation, not previously separated):
  **41.742 ms**.

Thus the ~354.564 ms excess was predominantly catalog discovery, not demonstrated
354 ms queueing. `DecisionSession` now measures admission, actual queue delay, preparation,
worker round trip, host validation and resumption separately. Worker round trip includes
catalog discovery and provider evaluation; these are **nested**, not additive
with worker round trip. Their sum with the other disjoint host intervals equals
blocking wait. Provider-start/answer timestamps, catalog time and actual encoded
POST-body bytes are retained separately. Timing is frozen at caller resumption;
late cleanup cannot mutate it. Cache hits do not reuse old RTT samples.

`timeline_ms` is relative to service entry; actual queueing is a separate stamp. Milestone-level detected,
queued, applied and resumed fields are relative to milestone detection. Timing
keys use `answer_received` to pass the existing strict display privacy boundary;
no privacy allowlist was weakened. The live probe found and repaired loss of ON
telemetry caused by a response-shaped field name; a real-worker-to-display
regression now covers that boundary.

No speculative evaluation is implemented: a terminal ordering decision cannot
save baseline agent reasoning, and eager calls would only increase utilization.
Existing within-session catalog/TLS reuse is preserved. No guessed warmup,
50-ms polling-floor claim, threshold reduction or hidden request retry is used.

## Reproduction and evidence interpretation

```sh
python -m unittest discover -s tests -p 'test_runtime_milestones.py'
python -m unittest discover -s tests -p 'test_decision_plane.py'
python scripts/probe_runtime_milestones.py --live \
  --output benchmarks/jev-pr31-milestone-final-probes.json
python scripts/benchmark_decision_plane.py --live --samples 1 \
  --output benchmarks/jev-pr31-milestone-final-component.json
python scripts/benchmark_decision_tasks.py --live --experimental-validation-order \
  --output benchmarks/jev-pr31-milestone-final-tasks.json
```

The hermetic runtime fixture uses real adapters, process supervision, Git and
unittest validators, with scripted agents/provider/receipts. Both Codex and
standalone Pi managed paths demonstrate completion -> Jev -> accepted changed
order -> actual host execution, with no subsequent agent decision. That is
integration-control proof, **not live provider quality or avoided reasoning**.

The live probes run real Codex and real standalone Pi under their existing
read-only policy. A marker request avoids demanding unavailable Pi tool
capabilities. All four OFF/ON marker tasks passed. Each ON runtime automatically
called Jev once at host completion; both fell back on uncertainty. No host
execution changed and no reasoning was offloaded. Final Codex/Pi RTTs were
283.920/286.215 ms; blocking waits were 659.500/631.421 ms. The final probe verifies
the exact final answer marker, not a substring anywhere in agent output. These
sparse cold calls are not suitable evidence for frequent automatic interception.

The matched task script preserves the original eleven scenarios and alternates
OFF/ON order. Its new explicit experiment switch and per-task milestone records
are separate from voluntary MCP calls. Original failed rows are retained; direct
component calls are never counted as runtime interception. Source fingerprints
identify the source tree used. One pair per case, provider load/caching and
unknown model turns/prices preclude causal speedup claims.

## Final repaired-source evidence

The final artifacts above and `jev-pr31-milestone-summary.json` correspond to
source fingerprint
`a482ca40f072d0aa2f26ed14af4154c7bff933f5baf98ba98e55d58375ac7550`.
Both live probes and the full matched matrix report an unchanged source during
execution. Earlier `jev-pr31-milestone-{tasks,probes,component}.json` files are
retained as **pre-repair exploratory observations**, not current-source proof.
Their old no-call `FALLBACK` convention is superseded by `PASSTHROUGH`.

| Measurement | Fresh paired OFF | Previous ON | Final experimental ON |
|---|---:|---:|---:|
| Total task latency | 305.471 s | 321.894 s | 319.543 s |
| Input tokens, including cached | 6,028,841 | 6,586,514 | 6,452,930 |
| Output tokens | 7,000 | 8,195 | 7,765 |
| Task success | 11/11 | 11/11 | 11/11 |
| Host milestones observed | 10 | unmeasured | 10 |
| Runtime Jev calls | 0 | 1 | 10 |
| OFFLOADED | 0 | 0 | 0 |
| ADVISORY | 0 | 0 | 0 |
| FALLBACK | 0 | 1 | 10 |

Final ON includes ten automatic host attempts, all completing evaluations; no
voluntary callable request occurred. All ten were uncertain, with no timeout or
cache hit. Generally these are supervised attempt counts: an interrupted request
without a received frame cannot prove that the provider received its POST. The
two separate live-probe calls are excluded from these totals. The historical OFF
reference supplied for the previous run was 327.630 s; the fresh OFF column
above is the matched control.

Runtime-call medians across ten samples: RTT **293.203 ms**, catalog
**312.479 ms**, actual queue **0.012 ms**, host decision validation **0.072 ms**,
blocking **655.891 ms**. Unavailable timeout RTT is always null, never zero.
Total automatic blocking was **6,475.207 ms**; useful overlap was **0 ms**. The
automatic state projection was 361 bytes; observed provider POST body 993 bytes.
ON was slower than its paired OFF run; no causal global regression or speedup
is established by one small matrix. The automatic category added measured
blocking without a single applied decision.

| Decision | Default automatic | Calls | Offloaded | Advisory | Fallback | Block ms | Automatic ROI |
|---|---|---:|---:|---:|---:|---:|---|
| Sequencing | No | 0 | 0 | 0 | 0 | 0 | UNPROVEN |
| Validation | No; explicit experiment only | 10 | 0 | 0 | 10 | 6,475.207 | NEGATIVE |
| Retry | No | 0 | 0 | 0 | 0 | 0 | UNPROVEN |
| Context | No | 0 | 0 | 0 | 0 | 0 | UNPROVEN |
| Progress | No | 0 | 0 | 0 | 0 | 0 | UNPROVEN |

The validation ROI concerns this automatic ordering candidate, not a verdict on
all future validation advice. Full local validation after the repairs passed:
773 tests, five platform skips, compileall, Python hygiene, public-artifact
policy and whitespace checks. Independent review attempt 1 timed out without a
final verdict. Review 2 found no concrete authority/cancellation bypass and
permitted retaining a draft, but correctly required repaired-source live
artifacts; the final reruns above resolve that evidence mismatch. This is not
approval to merge the unfinished feature.

## Promotion decision

No category is enabled by default. Validation-order ROI is **NEGATIVE for
reasoning offload**: it adds provider wait to a decision the host already made
without a model. A possible order-dependent diagnostic advantage is unproven.
Sequencing, retry, context and progress automatic ROI remain **UNPROVEN** and are
not implemented as automatic controls. Existing callable advice is preserved.

Highest-value remaining blocker: establish a policy-preserving **mid-turn
executable control boundary for both real Codex and standalone Pi** where a
bounded decision actually replaces an agent choice, then measure useful
accepted offloading. Do not substitute more terminal ordering calls, notifications,
advice exposure or a small aggregate ON improvement for that evidence.

Quattro final authority: YES. Quattro Intelligence final model authority: YES.
Jev and OmniRoute final model authority: NO. PR #31 remains draft/undeployed.
