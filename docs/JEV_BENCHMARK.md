# Jev routing benchmark — historical PR #30 evidence

This file preserves measurements from `b79900e7` **before canonical pipeline
unification**. Its all-turn shadow counts and harness-only classification
boundary are not current behavior. Current measurements, eligibility counts,
and the direct comparison with main #29 are in
[UNIFIED_TURN_ROUTING.md](UNIFIED_TURN_ROUTING.md).

Baseline main: `0f965b938e3c57a9f251103803743b8d46231981` (#29).
Python 3.14, local Linux; 20 repetitions × 8 task types = **160 samples per
mode per entrypoint**, 960 routing measurements in total. Benchmarks ran beside
repository tests; these are local observations, not production guarantees.

Commands:

```sh
python scripts/benchmark_jev.py --repetitions 20
python scripts/benchmark_jev.py --native --repetitions 20
```

**Hermetic simulation, not live Jev.** A real short-lived supervised child
simulates a 20 ms evaluation and returns schema-valid fixture signals. Actual
feature extraction, fusion, SQLite, target registry, process startup, and
lifecycle code run. Catalog latency is simulated as zero. No installed state,
provider credentials, native agents, or external services are used. An 80 ms
simulated execution interval gives shadow work time to finish; it is excluded
from routing latency. No active learned artifact exists in the isolated store;
reported learned timings measure the unavailable-artifact check, not inference.

## Final validation rerun

After the final deadline-accounting and cancellation-compatibility repairs,
the same commands were rerun (another 960 routing measurements):

| Entry | Mode | n | p50 ms | p95 ms | Added p50 vs OFF ms |
|---|---|---:|---:|---:|---:|
| Harness boundary | OFF | 160 | 0.262 | 0.335 | — |
| Harness boundary | SHADOW | 160 | 0.433 | 0.558 | 0.171 |
| Harness boundary | COOPERATIVE | 160 | 0.496 | 56.413 | 0.234 |
| Native TurnGate | OFF | 160 | 0.344 | 0.501 | — |
| Native TurnGate | SHADOW | 160 | 0.578 | 0.757 | 0.234 |
| Native TurnGate | COOPERATIVE | 160 | 0.687 | 57.802 | 0.343 |

Final native cooperative component p50/p95: simulated Jev 20.092/20.104 ms,
learned-unavailable check 0.014/0.027 ms, feature extraction 0.060/0.085 ms,
fusion 0.003/0.065 ms, explicit wait 0.001/57.196 ms (n=160 each).
Trivial DIRECT cooperative p50/p95: 0.538/0.627 ms (n=20), versus OFF
0.346/0.543 ms. Timeout/failure rates remained zero in all simulated enabled
runs; agreement and model distributions below were unchanged. Full validation:
671 tests, 5 platform skips; 37 focused Jev tests passed.

The following detailed breakdown preserves the preceding post-rebase run so
run-to-run variability remains visible rather than silently replacing evidence.

## Preceding run: aggregate critical-path routing time

| Entry | Mode | n | p50 ms | p95 ms | Added p50 vs OFF ms |
|---|---|---:|---:|---:|---:|
| Harness boundary | OFF | 160 | 0.264 | 0.333 | — |
| Harness boundary | SHADOW | 160 | 0.428 | 0.543 | 0.164 |
| Harness boundary | COOPERATIVE | 160 | 0.480 | 55.920 | 0.216 |
| Native TurnGate | OFF | 160 | 0.337 | 0.488 | — |
| Native TurnGate | SHADOW | 160 | 0.582 | 0.727 | 0.245 |
| Native TurnGate | COOPERATIVE | 160 | 0.685 | 55.713 | 0.348 |

COOPERATIVE aggregate p50 is low because policy skips waiting for DIRECT and
already-maximal tasks. **Eligible delegated tasks pay approximately 54–57 ms**
in this simulation, including process startup, not just the 20 ms evaluation.
This is not a claim of native Jev's RTT or a routing speedup.

## Native per-type critical path (20 samples per cell)

| Type | OFF p50/p95 ms | SHADOW p50/p95 ms | COOPERATIVE p50/p95 ms |
|---|---:|---:|---:|
| Trivial informational | 0.346 / 0.393 | 0.539 / 0.664 | 0.548 / 0.646 |
| Coding question | 0.414 / 0.488 | 0.628 / 0.695 | 0.649 / 0.752 |
| Repository modification | 0.278 / 0.347 | 0.501 / 0.921 | 54.790 / 56.051 |
| Frontend implementation | 0.298 / 0.382 | 0.533 / 0.661 | 54.404 / 56.386 |
| Debugging | 0.315 / 0.379 | 0.590 / 0.700 | 54.323 / 57.468 |
| Research | 0.466 / 0.608 | 0.646 / 0.745 | 0.683 / 0.749 |
| Complex coding | 0.312 / 0.359 | 0.556 / 0.726 | 0.624 / 0.698 |
| Review-only | 0.303 / 0.407 | 0.589 / 0.692 | 0.592 / 0.652 |

## Components, rates, and target distribution

Native COOPERATIVE p50/p95:

- Simulated Jev evaluation: **20.081 / 20.098 ms**, n=160.
- Local learned artifact-unavailable check: **0.014 / 0.026 ms**, n=160.
- Feature serialization/extraction: **0.064 / 0.083 ms**, n=160.
- Fusion: **0.003 / 0.064 ms**, n=160.
- Explicit critical-path wait: **0.001 / 55.018 ms**, n=160.

Native SHADOW evaluation: 20.077 / 20.099 ms; explicit wait 0.001 / 0.001 ms.
Do not sum parallel components or equate provider RTT with added routing time.

For each enabled mode/entrypoint, simulated timeout and failure rates: **0/160**.
Execution-signal agreement: **140/160**, disagreement **20/160**. The research
sample exposes a pre-existing difference: Quattro's execution gate says DIRECT,
whereas requirement-derived simulated Jev says DELEGATE. Policy keeps Quattro's
gate. This is evidence, not proof that either classification is human-correct.

Native selected model distribution:

- OFF and SHADOW: Luna 60, Terra 60, Sol 40.
- COOPERATIVE: Luna 60, Terra 40, Sol 60.

Harness boundary distribution:

- OFF and SHADOW: Luna 40, Terra 60, Sol 40, no eligible target 20.
- COOPERATIVE: Luna 40, Terra 40, Sol 60, no eligible target 20.

The harness research profile requires `research`, absent from the approved
registry. The benchmark reports that existing failure rather than weakening
capability checks. The latency-fixed native gate deliberately gives DIRECT
turns conversation-only capabilities, so the same sample has a native target.

## Example fixture decisions (not live model recommendations)

All examples use account-1; local learned signal is explicitly unavailable.

| Task | Simulated Jev execution/complexity/capability | Quattro constraint/policy | Final execution / worker / model / effort |
|---|---|---|---|
| Hello | DIRECT / LOW / CHEAP | Preserve direct gate | DIRECT / none / Luna / low |
| Modify repository parser | DELEGATE / MEDIUM / CHEAP | Cannot lower deterministic STANDARD | DELEGATE / codex / Terra / medium |
| Accessible frontend + tests | DELEGATE / HIGH / STRONG | Raise one tier; registry capability/cost filters | DELEGATE / codex / Sol / high |
| Complex migration | DELEGATE / HIGH / STRONG | Preserve existing REASONING ceiling | DELEGATE / codex / Sol / high |
| Research current docs | DELEGATE / MEDIUM / CHEAP | Execution signal cannot override direct gate | Native DIRECT / none / Luna / low |

Unit tests separately exercise an available learned DELEGATE signal, a confident
learned DIRECT veto, provider/account/capability rejection, failure fallback,
real-process timeout/cancellation/reaping, and unchanged latency-fix cases.

## Live limitations

**LIVE JEV TEST: BLOCKED — TYPESAFE_API_KEY unavailable.** Public OpenAPI was
retrieved, but authenticated `/v1/models`, canonical model identity, evaluation,
native network RTT distribution, actual usage and billing were not measured.
No live quality, calibration, success, cost, or promotion claim follows from
these fixture benchmarks. Official cost is unavailable in the documented API;
fixture token counts must not be presented as billable usage.

The rollout evidence gates are in [JEV_ROUTING.md](JEV_ROUTING.md). These local
results do not satisfy those gates.
