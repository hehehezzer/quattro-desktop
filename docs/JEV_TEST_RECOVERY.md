# Jev bounded test recovery — PR #31

This is the first executable mid-turn decision class. The global Jev mode may stay
`OFF`; `routing.jev.testRecoveryMode: COOPERATIVE` enables only this class. A
missing/`OFF` class mode preserves the native agent retry path. Linux is required
for this class because its test process-tree ownership depends on Linux
parent-death signaling. Windows Core remains supported with the class unavailable.
The separate
`experimentalTestRecovery` switch exposes the same tool with Jev OFF for matched
controls; it is not a production enablement setting. Validation-order and search
experiments are not production classes. The search experiment was removed from
source because Quattro could run both safe alternatives locally in milliseconds,
more cheaply than asking Jev.

## Runtime path

```text
managed Codex exec --json -> Quattro MCP quattro_test
standalone managed Pi -> explicit Quattro extension quattro_test
  -> fixed Python helper / policy-scoped MCP process
  -> Quattro validates tests/test_*.py basename and repository location
  -> bounded python -m unittest discover for that one file
  -> local cheap admission checks on actual failure
  -> Jev receives fixed failure category and duration bucket only
  -> typed choice: retry_exact | agent
  -> Quattro checks confidence, worktree freshness, budget, and action allowlist
  -> Quattro reruns the exact test at most once, with bounded output/time
  -> tool returns recovered result or original failure
  -> native Codex/Pi continues; required post-agent validation still runs
```

The native Codex bridge uses the existing decision-only TurnTransport proxy.
When global Jev is OFF, that proxy accepts only `test_recovery` if the class
mode is enabled. It still rejects stale, sensitive, cancelled, or non-delegated
turns. Routed Pi remains a Codex delegate and is not counted as standalone Pi.
Standalone managed Pi gets the explicit extension only under its run-scoped
`full-access-explicit` profile. The read-only Pi profile retains no native tools
and does not gain the test tool. Codex gets the tool only when its policy grants
workspace execution and network access. Pi's explicit full-access policy is
required for its network-capable test helper; ordinary writable Pi policies
remain rejected.

The host owns the interpreter path, test file restriction, argument vector,
working directory, 20-second per-command limit, 16 KiB output ceiling, single
retry limit, and process-tree cleanup. Linux helper processes have a parent-death signal.
No Jev text becomes a command. Quattro Intelligence's immutable provider,
account, model, effort, and DIRECT/DELEGATE plan are untouched. Jev's fixed
runtime request skips the cold catalog GET but still requires the POST response
to identify a narrowly validated canonical Jev model. No retry is made after
an ambiguous provider failure.

## Admission and response contract

The tool accepts only `test_file` as `test_name.py` or
`tests/test_name.py`, with a strict basename pattern and no symlinks. It runs
the test once before considering Jev. A pass returns immediately. Syntax/import
errors, timeouts, excessive output, assertions without a recognized delayed-wait
signal, and runs outside the measured 0.5–10 second window fall back without a
Jev call. Jev sees a fixed assertion category, duration bucket, one remaining
retry, and the two allowed actions. It never sees the full test output, code,
repository tree, conversation, credentials, or model route.

`DecisionSession` validates the native named-choice response and the chosen
action. The class requires confidence at least 0.65; `agent`, low confidence,
malformed output, unavailable provider, timeout, cancellation, or changed Python/config
file metadata returns the failed initial result for normal agent handling. The
freshness check never opens repository file content. A valid retry
is applied inside the same tool call, so the agent receives its outcome without
another model decision. A successful retry is reported as `recovered` but does
not certify the task or omit Quattro's mandatory validation. Telemetry separates
Jev calls, host-applied offloads, fallback reasons, provider RTT, blocking time,
request bytes, tool calls, task result, and agent model-step evidence.

## Authority

| Decision | Final authority |
|---|---|
| Execution policy, command, retry budget, and task success | Quattro |
| Final agent provider/account/model/effort | Quattro Intelligence |
| Bounded test retry recommendation | Jev, subject to Quattro validation |
| Final model routing | Never Jev or OmniRoute |

## Evidence and release gate

`python scripts/probe_test_recovery.py --samples 5 --output ...` runs real
managed Codex and standalone managed Pi in alternating OFF/ON order on fresh
prepared repositories. The fixture has a one-second ambiguous readiness
assertion that fails once and succeeds on retry. OFF requires the execution
agent to decide and run the retry; ON can do it inside the host tool. Both
modes must finish with the correct PASS answer and the normal harness task
validation. The script fingerprints the entire `src/` tree during the run,
records exact Git HEAD, measured provider blocking/RTT/payload bytes, task wall
time, tool calls, model-step evidence, and native token usage. Pi `turn_start`
events count model steps; Codex steps are a conservative inference from serial
native tool boundaries, because `codex exec --json` does not expose a separate
model-request count. A single fixture is not broad production quality proof;
negative/deterministic-failure and cancellation probes are required before
promotion.

Do not merge or enable the class on this document alone. Exact-head local and
hosted checks, independent review, live probes, matched ROI, and installed
parity are required.

### Candidate source benchmark (2026-09-27)

Five alternating matched pairs per host on unchanged `src/` fingerprint
`8bf78c2b8c35722d6ba669cf5af39e09df2158b298e1b0a80ba4cd2b51045dfb`
used the same fail-once fixture and the same source for OFF/ON. All 20 managed
tasks succeeded with the correct passing answer. Each ON host made five Jev
calls, accepted five bounded retries, and had zero fallbacks; each OFF host
required two test-tool calls, versus one ON. Pi emitted 15 OFF versus 10 ON
`turn_start` events. Codex has no exact model-request count in its JSON stream;
serial tool boundaries imply 15 OFF versus 11 ON model steps, but that is only
an estimate.

| Host | OFF total wall | ON total wall | OFF/ON median wall | OFF/ON input tokens | OFF/ON output tokens |
|---|---:|---:|---:|---:|---:|
| Codex | 102.315 s | 79.107 s | 21.195 / 14.878 s | 1,909,387 / 1,394,813 (mostly cached) | 1,035 / 936 |
| Pi | 66.194 s | 56.113 s | 13.550 / 10.434 s | 13,157 / 11,116 (plus cache reads) | 620 / 305 |

Codex ON was faster in four of five pairs; Pi ON was faster in four of five.
The Jev POST payload was 920 bytes per ON call. Median blocking was about
407 ms for Codex and 553 ms for Pi. These are narrow matched runtime results,
not a general latency guarantee. Exact committed-head CI and installed parity
remain release gates.
