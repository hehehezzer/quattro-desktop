**Current executable class:** [bounded test recovery](JEV_TEST_RECOVERY.md) adds a separately gated host-applied retry path. The advisory-only history below is retained for context.

## Current native/direct boundary (2026-09-30)

Direct native support is now a separate client-neutral advisory boundary in
`quattro_agent.native_intelligence`; it reuses this document's
`DecisionSession`, Jev client, credential resolver, taxonomy, deadlines,
confidence floor, cooldown, and fail-open behavior. It does not reuse the
managed launcher lifecycle or the managed `routing.jev` preference.

The native default is enabled only for the five implemented routine strategy
categories: `context_strategy`, `execution_strategy`, `validation_strategy`,
`retry_strategy`, and `progress_strategy`. Deterministic security, permission,
sandbox, model-selection, retry-limit, validation-success, and completion
decisions remain local/native. Unknown categories and semantic implementation
or root-cause reasoning remain with the native agent. `test_recovery` is not a
direct-native category.

Codex 0.158.0 has MCP but no supported ordinary-turn lifecycle callback. Its
native Jev integration is therefore the callable `operational_decision` MCP
tool configured in each effective Codex home. This is a supported tool
surface, not automatic interception. The MCP process owns a session-scoped
bounded `DecisionSession`; the response trace is returned to Codex, but
delivery to or reliance by the model is `UNVERIFIED`.

Pi 0.87.1's supported extension API provides `session_start`,
`before_agent_start`, `turn_start`, `tool_result`, `session_shutdown`, and
session commands. The native extension automatically admits at most one
non-trivial eligible decision per `before_agent_start`, after cheap local
signals select the relevant implemented category (`context_strategy`,
`execution_strategy`, `validation_strategy`, or `progress_strategy`). It sends
only minimized boolean/category signals to Jev and can apply an accepted
context `retrieve` answer by adding a bounded shared-retrieval message. The
extension keeps one lifecycle-owned helper for the Pi session so Jev worker
and catalog setup are reused; it is not a persistent daemon. Pi also exposes
the same `operational_decision` tool for later milestones. The host boundary
can confirm that the message or tool result was accepted; it still cannot
prove internal model reliance.

`QUATTRO_MANAGED_SESSION=1` suppresses the native operational tool for
managed Codex children. Managed Quattro continues to own its locked plan,
model/provider/account/effort, permissions, retries, validation, and existing
Jev behavior. Native shared knowledge does not grant any of that authority.

Native evidence is inspected with:

```bash
quattro-agent native status
quattro-agent native trace --session SESSION_ID --limit 100
quattro-agent native probe --directory "$PWD" --query "bounded diagnostic question"
quattro-agent native set --jev off
quattro-agent native set --jev on
```

The first command is passive and never calls Jev, retrieval, indexing, or
RTK. The trace requires an exact session id because concurrent sessions must
not be conflated. The probe is explicitly diagnostic and excluded from
ordinary-use metrics. Pi's session-local preference is
`/quattro-jev on|off|status`; it is persisted in Pi's native session and is
separate from the global native setting.

The evidence stages are intentionally conservative: configuration and loaded
integration are not use; retrieval answer delivery is distinct from source
selection and model reliance; an accepted Jev answer is not proof of action
application; RTK status is not RTK execution; cached results are not new
provider calls; and unavailable host stages are `UNVERIFIED` or `UNKNOWN`.
The local store is bounded, restrictive, concurrent-safe, and excludes raw
prompts, code, transcripts, credentials, full outputs, and absolute source
paths. Retrieval context token sizes are estimates, not exact provider token
counts.

# Jev runtime decision plane

## Current direct-native status (2026-09-30)

The installed direct-native integration is documented in
[NATIVE_SHARED_INTELLIGENCE.md](NATIVE_SHARED_INTELLIGENCE.md). Native Jev is
enabled by default for the five implemented routine strategy categories when
prerequisites are available, while explicit native OFF settings remain
authoritative. Direct Pi has a supported eligible-turn lifecycle call. Direct
Codex 0.158.0 has no supported ordinary-turn callback, so its supported path is
the model-selectable `operational_decision` MCP tool with a session-scoped
worker; it is not an automatic interception hook. Managed Quattro continues to
use its own locked execution authority and does not inherit native duplication.

The remainder of this file is the historical managed/runtime decision-plane
evaluation record. Its old experimental or production-OFF statements do not
describe the installed direct-native defaults above.

Historical continuation: [host runtime milestone experiment](JEV_RUNTIME_MILESTONES.md).

This extends, rather than replaces, [JEV_SPECULATION.md](JEV_SPECULATION.md).
The release is **not ready**. Production configuration remains unchanged/OFF.
MCP discovery is not proof of use, and useful advice is not proof of faster or
successful execution. The existing routing benchmark is not a task benchmark.

## Decision-point audit

| Boundary | Current owner / implementation | Treatment |
|---|---|---|
| Initial requirements, complexity, delegation evidence | `turn_routing.route_turn`, `routing_signals` | Existing early single Jev attempt plus local intelligence, unchanged |
| Final provider/account/model/effort | Quattro Intelligence / `model_registry`, immutable plan | Deterministic authority; no runtime decision service access |
| Permissions, capabilities, sandbox, scopes, budgets | `policy`, `adapters`, scheduler, supervisor, collaboration | Deterministic; never provider advice |
| User turns / native lifecycle | `TurnGate.begin/finish/cancel`, `CodexTurnBridge`, `pi-turn-gate.ts` | Host-owned state and invalidation |
| Operational context / sequencing / test order / retry triage / progress | New `operational_decision` MCP tool | Eligible, on-demand categorical advice during execution |
| Native Codex tools | Codex execution model; bridge observes item events | Observations invalidate advice; not a tool-authorization hook |
| Routed Pi | Pi input UI -> `/turn` -> durable **Codex** delegate | Same host decision service via a narrow loopback MCP proxy |
| Standalone/delegated Pi worker | Existing `PiAdapter`, read-only bounded worker policy | Unchanged; no native Pi decision extension added |
| Repository retrieval | Existing retrieval context assembly; subsequent agent work | Mandatory context remains mandatory; advice cannot omit it |
| Skill dispatch and exact file/tool arguments | Native agents | No new host skill dispatcher; no unsupported Jev name-selection claim |
| Architecture, implementation, root cause, synthesis | Execution agent | Semantic reasoning, not Jev replacement |
| Provider pressure retries and fallback models | `HarnessRuntime.run_task`, locked fallback plans | Existing hard bounds/eligibility/backoff unchanged |
| Validation and task completion | `validate_task`, validators, TaskStore | Host evidence only; Jev cannot certify either |

`decision_taxonomy.py` separates DETERMINISTIC, JEV_ELIGIBLE and AGENT_REASONING.
Unknown types default to agent reasoning. Eligibility is not implementation:
only the five fixed strategy vocabularies currently have provider questions.
Unsupported eligible types (including exact skill/tool selection) fail open.

## Actual runtime mechanism

```text
initial prompt -> existing early Jev/local fusion -> Quattro Intelligence plan
                                                       |
                  native Codex or routed Pi -> Codex execution
                                                       |
                         meaningful operational decision
                                                       |
                          operational_decision MCP tool
                                                       |
        native session: authenticated existing /decision endpoint
                                                       |
                  TurnGate-owned DecisionSession / one owned worker
                                                       |
                  fixed-origin TypeSafe named choice question
                                                       |
       validated usable advice OR explicit fallback -> execution agent
```

The agent is instructed through the MCP server/tool contract to prefer this
service over lengthy deliberation for suitable operational milestones, not
every action. It still chooses when to call, applies permitted actions, and
handles deep reasoning. This is an explicit callable interception surface,
not automatic interception of opaque internal model reasoning. Exposure alone
cannot establish that agents routinely use it.

Supported runtime choices:

- `context_strategy`: inspect, retrieve, sufficient context, or agent reasoning;
- `execution_strategy`: sequential, parallel candidate, or agent reasoning;
- `validation_strategy`: targeted-first or broad-first (both retain all required checks);
- `retry_strategy`: retry candidate, change strategy, or agent reasoning;
- `progress_strategy`: continue, validate, more context, or agent reasoning.

No action executes a command, starts a worker, changes a model, grants a
permission, marks a validation passed, or completes a task. `hard_constraints`
in tool input are additional caller-supplied restrictions, **not authorization**.
All actions require the existing host controls when executed. An agent cannot
turn a supplied `retry_allowed=true` into a host retry-budget increase.

## Lifecycle and integrations

`decision_launch.py` scopes launcher options with ContextVars. Existing harness
Jev lifecycle scopes carry those options into `CodexAdapter`; ordinary CLI
execution registers a local MCP service only under COOPERATIVE mode and an
already network-capable policy. Read-only/limited standalone workers are not
silently granted direct provider access.

`native_session.py` registers a proxy on the Codex backend, not the remote TUI.
Routed Pi's existing Codex delegate receives that proxy through explicit
LaunchPlan environment overrides. The proxy only calls Quattro's existing
decision-only authenticated loopback endpoint; its separate capability cannot
submit turns, cancel work or call the model transport. TypeSafe credentials
remain in the Quattro owner. Tokens are environment/anonymous-pipe values, never argv or
telemetry. Pi UI tool restrictions and native approval policy are unchanged.
The tool truthfully declares read-only/non-destructive MCP annotations; there
is no automatic approval override.

`TurnGate` owns the service across ordinary turns. Cancellation/shutdown signals
monitor-owned termination and reaping; a later turn can create a fresh service.
Interactive turn cancellation calls `request_close()`, which signals shutdown
without joining the monitor, so Jev cleanup cannot delay model socket interruption.
Session teardown calls `close()` and joins for at most five seconds, never
acquiring the worker lock or performing kill/reap/stream operations. If an OS
wait ignores its timeout, the daemon monitor retains the process and capacity
until death is observed, without preventing host exit. A regression explicitly
blocks `wait()` on an event, verifies bounded close and no replacement worker,
then releases it and verifies exactly-once capacity release. A single
persistent monitor thread owns child creation: Linux parent-death SIGKILL is
bound to the creating OS thread, so a per-request creator would incorrectly
kill a reusable child at the end of every call. A real-worker regression covers
this, not just a simulated subprocess lacking parent-death behavior.

One verified TLS connection and catalog are reused for the runtime worker's
lifetime. Stale sockets fail open without replaying a POST; subsequent eligible
calls can start a fresh worker. Existing initial routing still has its original
worker and one-attempt fusion contract; it is not rewritten to use this service.

## Input, freshness and authority

The live OpenAPI contract supports named `choice` questions in
`POST /v1/systemone`. No unsupported free-text reason, arbitrary tool schema,
model-selection response, or execution API is invented. `evidence` is a local
fixed category; native confidence/probabilities remain distinct.

Only allowlisted booleans and categories cross the provider boundary: no raw
prompt, code, path, tool output, history, selected route or credential. The
native owner reuses the initial feature projection without another extraction.
Completed high-confidence initial Jev complexity/task-type answers can also be
reused as **initial task context**, never as a current next-action decision.
Current result/phase signals remain distinct.

The host replaces caller revisions with its own monotonic revision. Native
Codex tool start/completion events, turn changes and cancellation invalidate
in-flight advice. Concurrent/ambiguous active turns fail open. Opaque delegated
Pi internals cannot provide that same item-level observation, so no cross-call
runtime-action caching is enabled. The standalone callable likewise does not
trust model-supplied revisions enough to cache actions. The service's optional
exact-projection cache is restricted to callers explicitly asserting a trusted
revision; production MCP paths do not opt in. New revision, changed projection,
closed service or a stale revision prevents reuse.

Authority remains:

- Quattro final authority: **YES**.
- Quattro Intelligence final model authority: **YES**.
- Jev final model authority: **NO**.
- OmniRoute final model authority in the locked execution paths: **NO**.

Existing explicit legacy gateway mode is not promoted or modified.

## Bounds, failure and measurements

The existing configurable 100–3000 ms request limit (default 1500 ms) is reused;
no 25 ms default is introduced. A single-flight caller deadline includes worker
startup and lookup, not just HTTP socket time. A lifecycle-owned monitor may
finish cleanup after the caller has already fallen back. New calls cannot queue
behind retiring work. Shutdown separately joins cleanup. Kernel/filesystem and
thread scheduling are not hard-real-time guarantees.

Resource bounds: one worker per service, existing eight-worker process-local
capacity, 64 evaluation attempts per service, bounded input/output frames,
three-failure/30-second cooldown, no automatic POST retry. These are safety
ceilings, not claimed optimal performance constants or a calibrated runtime
quality policy. The inherited 0.90 confidence floor is conservative and not a
runtime accuracy certification.

Timeout, missing authentication, provider errors, invalid/malformed response,
low confidence, unsupported decision, contention, stale state and hard-constraint
conflict produce normal-execution fallback. Cleanup retains ownership of an
unreaped child; dead-child cleanup releases capacity even if pipe closure fails.
The initial routing early-start/reuse/wait-budget/transport/timing regressions
remain part of the full suite.

Per-session metadata includes attempts by decision type, completed evaluations,
accepted usable answers (not proven actions taken), skipped/fallback reasons,
cache hits, deadline misses, errors, token usage, worker starts, actual blocking
wait and last observed network/catalog RTT. Native turn telemetry includes this
snapshot, initial-context reuse and separate post-freshness per-turn outcomes;
service-level usable answers are not automatically host-accepted answers.
Unobserved agent overrides, turns avoided
and prices are null. There is no speculative runtime overlap claim: the current
runtime callable waits at its chosen boundary; initial routing remains separately
speculative. Provider work settled after a deadline is not useful overlap.

## Evidence and remaining gates

```sh
python -m unittest discover -s tests -p 'test_decision_plane.py'
python scripts/benchmark_decision_plane.py --live --samples 3 \
  --output benchmarks/jev-pr31-decision-component.json
```

The component benchmark covers eleven scenario categories, balanced OFF/ON
ordering, real worker/client reuse and actual TypeSafe responses. It does **not**
run an execution model or establish task success, first token, model tokens,
total-task latency or savings. Unsupported skills and trivial questions skip
provider work. Failed/uncertain decisions must not be counted as useful answers.

Exploratory real Codex task pilots also exercise registration and actual calls.
Early pilots exposed missing read-only MCP annotations and a benchmark fixture
that incorrectly required `.git` mutation from the agent sandbox. Neither is a
reason to weaken approval/sandbox policy. The fixture must arrive on its own
prepared task branch. A failed task finishing sooner is not an improvement.

### Live task and native-protocol observations

`benchmark_decision_tasks.py --live --output ...` runs eleven disposable,
prepared-branch task scenarios through real Quattro/Codex execution, plus the
native DIRECT path for a trivial question. Ordinary task prompts do not force
Jev calls. The one-worker budget deliberately prevents actual subagent spawning;
this is a synthetic smoke matrix, not a representative parallel-work benchmark.

`benchmarks/jev-pr31-task-smoke.json` preserves all 22 original observations:
OFF succeeded in 10/11; COOPERATIVE succeeded in 11/11. The failed OFF skill
fixture encountered `scheduler_failed` before execution and remained ready;
its owned task was subsequently cancelled. Its short duration is **not** a
performance win. A separately preserved follow-up passed in both modes.

For the ten original scenarios successful in **both** modes:

| Measurement | OFF | COOPERATIVE |
|---|---:|---:|
| Sum of task wall time | 243.914 s | 286.689 s |
| Median task wall time | 26.718 s | 33.179 s |
| Reported input tokens (cached subset included) | 5,514,372 | 6,072,120 |
| Reported cached input tokens | 5,163,776 | 5,705,472 |
| Reported output tokens | 6,458 | 7,963 |
| Reported reasoning output tokens | 1,382 | 2,256 |
| Runtime Jev calls / usable answers | 0 / 0 | 1 / 1 |

The single runtime answer was `execution_strategy=sequential`, confidence 0.94,
with 644.621 ms blocking, 262.125 ms provider RTT and zero speculative runtime
overlap. It is evidence of default tool use, not causal savings or proven agent
adherence. Other model turns, overrides, unnecessary tool calls and prices were
not measured. Model input caching and concurrent provider load differ. ON was
**observed slower**, not faster; no benefit or non-inferiority claim follows.
The matrix predates the final shutdown-only repair; the skill follow-up and
native probes use the repaired source fingerprint recorded in their artifacts.

`benchmarks/jev-pr31-native-smoke.json` records successful real Codex app-server
execution through the bridge and successful real Pi JSON frontend execution
through its durable Codex delegate. Both made a validation-strategy call through
the decision-only proxy, reused initial context, and safely fell back on low
confidence. Codex observed seven model requests. Pi's delegated model-request
count is unavailable, not zero. These are source-tree protocol probes, not
installed-runtime, graphical TUI, resume, or production-readiness proof.

### Original candidate review and promotion status

Three independent read-only review iterations were used, reaching the authorized
limit. Findings repaired: caller deadlines including slow cleanup; retained
worker ownership and active late reaping; thread-scoped Linux parent-death
behavior; narrow proxy authority; host freshness; and finally monitor-only
shutdown with an indefinitely blocked-wait regression. The final shutdown repair
has local tests but **no subsequent independent re-review**. Do not describe
that review gate as passed or silently start a fourth iteration.

Remaining gates: independent verification of the last repair within newly
authorized review scope; representative successful matched-task evidence with
routing/model quality and unnecessary-tool/retry checks; exact-head local and
hosted validation; merge; existing deployment mechanism; installed Codex/Pi
lifecycle proof. This candidate establishes a bounded advisory integration, not
a demonstrated faster session-wide production decision plane. No merge,
production deployment or default enablement is implied by this document.

### Exact-HEAD continuation: cancellation repair and fresh evidence

Continued `ebee9ed34fbd9df6c20729e61b9e6eed37f37d4f`, without replacing the
existing integration. Under the renewed continuation request, independent review
found that the five-second `close()` join ran before model socket interruption.
The repair splits non-joining `request_close()` from teardown `close()` and uses
the former in `TurnGate.cancel()`. Monitor ownership and capacity retention are
unchanged. A real-worker integration regression holds reaping indefinitely,
requires cancellation/socket interruption before releasing the hold, then proves
exactly-once capacity release. A second independent read-only review found no
material findings within this repair's scope; this is not approval of the entire
feature. Full local validation: 757 tests, five skipped, plus compileall, Python
hygiene, public-artifact policy, and whitespace checks passed.

Fresh evidence:

- `benchmarks/jev-pr31-continuation-component.json`: one eleven-case component
  pass on the starting HEAD, nine actual evaluations, three usable answers.
  ON RTT median/p95 288.202/323.386 ms; blocking median/p95
  297.895/637.100 ms (including the unsupported-type skip in blocking samples).
  This is not task latency. Runtime overlap remains zero.
- `benchmarks/jev-pr31-continuation-tasks.json`: real Quattro/Codex task matrix on
  the repaired source, with an unchanged source fingerprint throughout. OFF and
  ON both succeeded on all eleven scenarios. Total wall time sums were
  327.630/321.894 s; medians 37.834/31.382 s. Input tokens were
  6,678,994/6,586,514 (cached subset 6,309,376/6,206,208); output tokens
  7,866/8,195; reasoning output tokens 1,672/1,793. ON made only one runtime
  call, returning fallback at confidence 0.50 after 637.289 ms blocking and
  282.724 ms RTT. No runtime advice was accepted. This run does not demonstrate
  routine offloading, token savings, or causal latency benefit. First-token
  latency is available only for the trivial DIRECT scenario; model turns and
  cost remain unavailable.

The objective remains incomplete: operational advice is still agent-invoked,
standalone Pi has no runtime integration, and there is no demonstrated
session-wide decision contribution or representative parallel-work benchmark.
These are engineering/evidence gaps, not external authorization blockers. The
PR stays draft and production stays unchanged/OFF. Do not merge or deploy this
increment as fulfillment of the decision-plane objective.
