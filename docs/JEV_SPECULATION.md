# PR #31: speculative routing increment (not release completion)

## Changes and authority

Eligible canonical routing now starts the existing owned Jev worker before
account availability, runtime health filtering and baseline candidate ranking.
Successful target selections are reused within the turn's immutable runtime
snapshot, not cached across turns. Learned inference remains
active. The fusion boundary consumes that exact attempt, including a failed or
suppressed attempt, without a duplicate request. Request deadlines start at
worker ownership, not again after local preparation. Immutable plans and all
local deterministic constraints remain unchanged.

`timeoutMs` now defaults to 1500 ms rather than 300 ms: measured healthy catalog
plus evaluation and interpreter startup exceed 300 ms. Explicit existing values
are preserved. Optional `decisionWaitMs` independently limits routing's wait.
Expiry does not count as provider failure, kill a healthy request, or mutate a
plan later. The native turn still owns finish/cancel/shutdown cleanup. Full
adaptive certainty/consequence/cost policy is **not yet implemented**; omission
of the optional budget preserves the full request wait.

Jev final authority: **NO**. Quattro final authority: **YES**.
OmniRoute routing authority in locked passthrough mode: **NO**.

## Real measurements

No raw prompts, credentials, provider bodies or execution outputs are logged.
Fixtures are synthetic and source-controlled. All successful evaluations return
`jev-1.13.0`. These are **routing-only**, not user-visible execution benchmarks.
No task-success, first-token, total-task duration, price or economic benefit is
established. Ten samples are exploratory; no final performance gate is set.

Commands:

```bash
python scripts/benchmark_jev_live.py --samples 20 --timeout-ms 1500
python scripts/benchmark_jev_live.py --samples 10 --timeout-ms 1500 --decision-wait-ms 25
python scripts/benchmark_jev_live.py --samples 10 --timeout-ms 1500 --decision-wait-ms 100
python scripts/benchmark_jev_transport.py --samples 10
```

The benchmark covers eleven task categories plus DIRECT → DELEGATE → DIRECT
as three successive turns. OFF/ON ordering alternates within each run. Old
synchronous source was archived from `f5c3ce2` and used the same expanded
benchmark script/fixtures, with no source-policy changes. Architecture runs
were separate, not time-interleaved; network variance remains a confounder.

Checked-in aggregate artifacts contain every case's p50/p95, route, execution,
fusion and available timing fields (unmeasured values are null):

- `benchmarks/jev-pr31-synchronous.json`: OFF and old synchronous cooperative,
  20 repetitions, 280 turns/mode, 80 live evaluations, no failures.
- `benchmarks/jev-pr31-speculative-reuse.json`: OFF and speculative cooperative
  with within-worker connection reuse, 20 repetitions, 280 turns/mode,
  80 live evaluations, no failures. This run preceded the final small
  per-turn candidate-preparation/cache follow-up, which has hermetic coverage
  but no new live performance claim.
- `benchmarks/jev-pr31-wait25-experiment.json` and
  `benchmarks/jev-pr31-wait100-experiment.json`: 10 repetitions each using the
  original urllib transport, 40 live attempts each. The 25 ms run observed one
  fixed-category HTTP failure; 100 ms observed none. Both explicitly settle
  late Jev work **outside routing** to measure RTT; settling is not execution
  and must not be reported as useful overlap or total-task duration.
- `benchmarks/jev-pr31-transport-experiment.json`: balanced rotated transport
  comparison, 10 actual evaluations per transport, catalog verified every time.

### Before / after, full normal wait (p50 / p95 ms)

| Measurement | Synchronous before | Speculative + connection reuse |
|---|---:|---:|
| Live Jev evaluation RTT | 356.716 / 397.521 | 281.613 / 315.550 |
| All-turn routing wall time | 0.386 / 727.329 | 0.393 / 654.068 |
| Ambiguous DIRECT routing | 698.810 / 727.329 | 623.552 / 671.108 |
| Debugging routing | 719.692 / 765.648 | 633.494 / 674.956 |
| Backend routing | 705.360 / 738.967 | 633.141 / 659.092 |
| Sequence DELEGATE routing | 705.683 / 746.371 | 627.254 / 655.863 |
| Trivial DIRECT routing | 0.249 / 0.350 | 0.248 / 0.344 |
| All-turn actual Jev wait | not instrumented | 0 / 653.407 |
| Evaluation overlap with local preparation | not instrumented | 0 / 0 |

Per eligible case after reuse:

| Case | Actual wait | Local routing | Fusion |
|---|---:|---:|---:|
| Ambiguous DIRECT | 622.830 / 670.439 | 0.643 / 0.719 | 0.007 / 0.009 |
| Debugging | 632.933 / 674.353 | 0.549 / 0.597 | 0.007 / 0.008 |
| Backend | 632.505 / 658.421 | 0.595 / 0.618 | 0.008 / 0.010 |
| Sequence DELEGATE | 626.608 / 655.276 | 0.549 / 0.665 | 0.007 / 0.008 |

The all-turn median hides eligible latency because existing broad guards skip
most fixtures. Attempt counts per turn: median **0**, p95 **1**, maximum **1**;
eligible turns are uniformly one. Counts measure supervised worker attempts,
not a claimed HTTP evaluation when a worker dies before POST. Successful live
runs issue one catalog GET and one evaluation POST, without retries.

Crucially, speculative scheduling alone showed **zero measurable evaluation
overlap**: local work finishes before Python/catalog preparation reaches the
POST. The RTT reduction above is connection reuse, not hidden latency.
Do not claim the substantial-overlap objective is achieved.

Bounded waits decouple RTT from routing: with 25 ms configured, live evaluation
RTT was 356.669 / 383.787 ms while all-turn routing was 0.377 / 25.679 ms.
With 100 ms configured, routing was 0.383 / 100.690 ms. Neither budget obtained
a timely Jev answer with this cold-worker path. These are experiments, **not
validated adaptive defaults** or evidence of preserved task quality.

## Client lifecycle audit

Current production source implementation:

- Persistent **session** client: **NO**.
- Persistent process: **NO**.
- Connection reuse: **YES**, between catalog and evaluation in one owned worker.
- One bounded fixed-origin HTTPS connection; verified default TLS and HTTP/1.1.
- No proxy inheritance, redirect following, retry or alternate model selection.
- Explicit close on worker completion/failure; owner cancellation kills/reaps
  the process. A stale connection falls back locally; next turn creates a fresh
  connection. No background reconnect loop or detached process.

Live transport-only p50/p95, excluding child startup:

| Transport | Catalog + evaluation wall | Evaluation RTT | Connections |
|---|---:|---:|---:|
| Existing urllib, fresh per request | 665.944 / 680.467 | 364.293 / 385.711 | not instrumented |
| HTTP/1.1 reuse within each turn | 569.714 / 595.928 | 270.804 / 289.238 | 10 for 10 turns |
| Experimental session connection | 510.172 / 565.284 | 283.759 / 320.108 | 1 for 10 turns |

The experiment proved enough benefit to adopt the small within-worker reuse
change. Session reuse also looks beneficial, but its IPC supervision,
cancellation/recovery and ownership are not implemented or lifecycle-validated;
the experiment is not a persistent-worker deployment.

On the final 80-request source run, process creation was 0.218 / 0.258 ms;
combined interpreter/module startup was 35.130 / 37.175 ms; HTTP client
construction was 3.860 / 4.148 ms. Catalog RTT was 298.284 / 309.551 ms.
DNS/TCP/TLS connect was measured only as a combined transport experiment stage
(72.927 / 76.922 ms for fresh per-turn HTTP/1.1). Separate DNS, TCP, TLS and TLS
session-resumption attribution is unavailable. System DNS caching is not
assumed. Keeping a socket demonstrably avoids another connect.

## Reuse and cache audit

A turn's fusion consumes one Jev response; downstream locked-plan ingestion
already avoids reclassification. Current four-question schema is still not the
requested broad bundle. Local classification/profile extractors still have
redundancy; they were not removed under an assumption that Jev replaces local
intelligence. The cache remains **unimplemented**: these repeated synthetic
fixtures would artificially inflate hit rate, and there is no representative
runtime-state/schema/model invalidation or route-quality evidence yet. No raw
prompt cache key or sensitive digest was introduced.

## Validation

Full local suite: **735 tests, 5 skipped**. Compileall, Python hygiene,
public-artifact policy and whitespace checks passed. Eleven added regressions
cover startup before health/learned/candidate work, single attempts, preserving
local errors, request deadline accounting, independent budget expiry, config
bounds/defaults, interval-based timing, fixed-origin redirect rejection,
connection reuse/close and stale-connection failure without retries. Existing
cancellation, shutdown, OFF and resume coverage remains green.

Direct self-review performed; independent review is outstanding because this
session has no delegation tool. Hosted exact-head CI is recorded on PR #31,
not inferred from local results. No merge or deployment has been performed.

## Remaining PR #31 gates

This increment does not finish the requested feature. Remaining work includes:
minimal-projection startup before all independent canonical profiling; bounded
supervised session client/worker if justified after lifecycle tests; narrow
adaptive guards/default waits; full decision bundle and downstream reuse;
launcher ON/OFF + enabled default + Enter + native session/resume persistence;
complete dispatch/first-token/total-task telemetry; end-to-end model/task/cost
quality comparison; independent review; exact-head release validation; merge,
deployment and installed-runtime verification. Production remains unchanged.
