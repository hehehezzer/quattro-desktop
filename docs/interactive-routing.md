# Native interactive routing

Quattro owns each turn's execution decision independently of the selected UI.
Supported native versions validated for this change: Codex 0.157.1 and Pi 0.87.1
(Node 24). The Codex remote bridge currently requires a Unix socket platform.

## Cause and corrected boundary

The former `native_interactive_handoff` called `os.execvpe` with the native CLI.
Quattro classified no subsequent user turns. The frontend consequently selected
the execution environment; ordinary questions inherited its model, instructions,
tools, retries, and agent loop. The previous persistent-plan rejection guarded
managed task entrypoints but did not guard this native launch path.

That confirms the architectural cause of the regression. The reported 9m20s
turn could not be identified reliably, so its exact time split between provider,
reasoning, retries, and tools is **unknown**. The change does not claim otherwise.

Old path: chooser → native CLI → native agent loop → configured transport.

New Codex path: chooser → real Codex TUI → private Quattro WebSocket app-server
bridge → fresh turn classification and immutable plan → DIRECT Responses call
or delegated native app-server turn. The bridge never forwards a DIRECT
`turn/start` to the native backend.

New Pi path: chooser → real Pi TUI → trusted pre-agent input hook → the same
Quattro gate → DIRECT Responses call or durable Codex harness task. Every input
is consumed by the hook, including failures, so an unavailable gate cannot fall
through to native Pi execution.

## Plans, budgets, and transport

A session identity lasts across turns. Each turn gets a new UUID and immutable
ExecutionPlan; completed/cancelled plan IDs are rejected by transport. Concurrent
turns in one thread are rejected; separate native threads have separate plans.
The latest user request, not the frontend or the preceding turn's tier, controls
DIRECT versus DELEGATE.

DIRECT/FAST has a 20-second wall budget, including routing, preflight, transport,
and receipt lookup. DIRECT/STANDARD has 60 seconds and DIRECT/REASONING reserves
90 seconds. The current direct classifier uses FAST or STANDARD. DIRECT uses
no repository scan, task database, retrieval, subprocess agent, or tools. It has
no automatic retries or target fallback. Budget expiry fails promptly and closes
its active socket. The user can retry explicitly.

DELEGATE has no conversation-wide deadline. Existing durable harness policy
limits remain applicable to Pi-fronted delegated tasks. Native Codex transport
has a 180-second per-request bound; this does not impose a total coding-task
limit. Native retries retain the same immutable target. Quattro retains model
and account authority; no legacy gateway routing is enabled.

Delegated requests must include their active plan ID. Quattro replaces model,
effort, and routing envelope at its private transport and verifies the gateway's
receipt before releasing actionable model output. This currently buffers at
most 4 MB per delegated model response, so native token-by-token display is
batched until the receipt is verified. OmniRoute's streaming, provider cache,
optimization, and accounting still operate.

## Native state and compatibility

`quattro-agent`, `launch`, `launch codex`, and `launch pi` retain the real selected
interface and terminal. Codex approvals and tool execution use its native backend.
Its native history retains delegated work. DIRECT responses are injected into
native model context; a private bounded overlay preserves the latest 100 DIRECT
turns for native resume display. Native read/resume data hydrates bounded recent
DIRECT context without a new repository or memory lookup.

Pi uses a native session file initialized from an empty private file. Its
ordinary routed messages persist as native custom messages. Bounded recent
history is sent back to the gate on subsequent/resumed inputs. Sensitive answers
use transient widgets. Quattro's existing logical Pi resume limitation remains;
a native Pi session reference is required for native resume.

Steering/queued generation, compaction, native review/goal generation, and
attachments currently fail explicitly when they cannot obtain a fresh plan.
Submit the work as a new ordinary turn. Pi shell shortcuts, compaction, new/fork
session operations, and native cache warming are blocked because they bypass
input routing or native custom-message persistence. Start a new Quattro session
instead. No unsupported path silently falls back to unclassified execution.

## Secrets and evidence

Credential lookup requests stay DIRECT. No general filesystem search is used.
There is currently no approved local credential lookup provider, so the response
states that limitation without calling a model. Embedded recognizable credential
values are rejected before persistent delegated execution. Detected sensitive
DIRECT requests/responses are excluded from history injection/overlay and Pi
persistent messages. Native Codex input-history persistence and prompt telemetry
are disabled for these scoped launches.

Operational JSONL contains allowlisted session/turn IDs, frontend, decision,
profile, target, effort, reason code, tool/lifecycle flags, timing, status, and
fallback metadata. It contains no prompt, response, exception text, or content
fingerprint. This telemetry is separate from training observations.

Legacy durable/historical `interactive` and `resume` evidence receives
`frontend_forced_execution` provenance during dataset projection. Forced
production decisions/outcomes and nonblind derived labels are excluded;
independent blind human classification is retained. Raw database records and
immutable historical files are preserved. Unsafe old snapshots must be rebuilt
before training/promotion.

## Measured local performance

2026-09-26, approved Account 1 Luna target, real OmniRoute transport, synthetic
prompts. Values are observations, not latency guarantees. Router time excludes
session startup; dispatch time is preparation between routing and model request.

| Case | Router | Dispatch preparation | First token after dispatch | Total | Agent loop |
| --- | ---: | ---: | ---: | ---: | --- |
| API gateway definition | 0.986 ms | 8.331 ms | 1,469.978 ms | 2,224.031 ms | No |
| Dashboard credential request (no approved lookup) | 0.307 ms | N/A | N/A | 0.452 ms | No |
| Python traceback explanation | 0.205 ms | 1.913 ms | 1,545.171 ms | 4,670.389 ms | No |

The metadata-only artifact is [interactive-turn-2026-09-26.json](../benchmarks/interactive-turn-2026-09-26.json).

Separate actual native Codex UI smokes measured DIRECT at 2.49 seconds and a
read-only delegated repository inspection at 5.29 seconds. The latter used tools
and verified its locked receipt. A native UI restart/resume displayed a persisted
DIRECT answer. A single real native TUI session also completed DIRECT → DELEGATE
→ DIRECT in 2.48s, 7.65s, and 2.40s with three distinct plan IDs and tools only
in the middle turn. No reproducible controlled before measurement exists for the
reported 9m20s request.

Reproduce synthetic direct measurements without retaining answer content:

```sh
python scripts/routing/benchmark_interactive.py --live --account account-1
```

Hermetic regressions cover the requested A–F decisions, frontend independence,
plan expiry, native bridge frames/rendering/history, cancellation, secret
exclusion, locked receipts, evidence provenance, and Pi's fail-closed hook.
