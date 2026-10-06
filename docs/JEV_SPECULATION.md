# Jev timing and retired speculation experiments

Current behavior is the [v2 model-authored decision plane](DYNAMIC_DECISIONS.md).
Initial host routing does not issue a speculative fixed questionnaire. The
executing native model supplies the decision content through
`operational_decision` when current evidence warrants consultation.

The session-owned worker may reuse established transport and catalog state
within its existing ownership boundary. Single-flight admission, request wall
deadlines, cooldown, bounded worker capacity and shutdown still apply. No
provider POST is automatically retried. A late or cancelled answer cannot
revise an already locked execution plan or certify completion.

Timing separates provider round trip, worker round trip and caller blocking
where those stages were actually observed. Provider latency is not a task
speedup, and unavailable timing remains unavailable. Delivery, accepted advice
and actual application require separate evidence.

## Authored diagnostics

`scripts/benchmark_jev_live.py --decisions-stdin` accepts a bounded authored v2
object or sequence through private stdin. `scripts/benchmark_jev_transport.py
--decisions-stdin` uses the same input boundary and allocates each supplied
envelope once to a transport in round-robin order. Neither script generates
questions, retains raw content, invokes an execution model, or retries a
failed provider request. See [JEV_BENCHMARK.md](JEV_BENCHMARK.md).

## Retired historical evidence

The earlier speculative-routing and dispatch-wait experiments are retired.
These records retain their original measurement scope and limitations:

- [Synchronous experiment](../benchmarks/jev-pr31-synchronous.json).
- [Speculative reuse experiment](../benchmarks/jev-pr31-speculative-reuse.json).
- [Short-wait experiment](../benchmarks/jev-pr31-wait25-experiment.json).
- [Longer-wait experiment](../benchmarks/jev-pr31-wait100-experiment.json).
- [Transport experiment](../benchmarks/jev-pr31-transport-experiment.json).

They measured an obsolete fixed-question routing path. They do not establish
performance, usefulness, live acceptance or deployment of the current v2
interface. Historical command lines and case menus are no longer supported.
