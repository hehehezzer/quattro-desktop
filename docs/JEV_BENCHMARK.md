# Jev diagnostics and retired routing benchmarks

Current diagnostics require the
[model-authored v2 contract](DYNAMIC_DECISIONS.md). No benchmark supplies a
built-in decision category, question, option list or feature questionnaire.

`scripts/benchmark_jev.py` is retired and exits with a retired status without
provider access. Its former simulated routing benchmark cannot be used as
current provider, native adoption or speedup evidence.

`scripts/benchmark_decision_plane.py` is also explicitly retired. It no longer
imports the removed taxonomy or manufactures fixed provider questions.

`scripts/benchmark_decision_tasks.py` retains its opt-in synthetic task smoke
matrix. Its cases are execution tasks, not provider decision alternatives. The
native execution model authors any v2 decisions; aggregate reports export only
validated host effects, never authored option identifiers or probability keys.
`scripts/probe_runtime_milestones.py` remains an opt-in native completion and
mandatory-validation smoke test. Legacy validation-order settings perform no
provider consultation or reordering. Neither smoke test establishes a speedup.

## Explicit authored input

`scripts/benchmark_jev_live.py --decisions-stdin` reads one authored envelope or
a JSON array of at most 64 envelopes from bounded private stdin. The sequence
has a 512 KiB input ceiling and every envelope is independently validated within
the 8 KiB decision bound. Empty, legacy, malformed, duplicate-key or excessive
input is rejected before credential lookup or provider work.

Each supplied envelope is admitted once to the bounded session decision service.
There are no provider retries, invented alternatives or execution-model calls.
The script has no attested execution-tool capability map. Capability-dependent
choices cannot gain permission from benchmark input. Reports distinguish authored
decisions, confirmed provider attempts, accepted advice, failure evidence and
measured timing. They exclude authored questions, options, context and raw
provider bodies.

`scripts/benchmark_jev_transport.py --decisions-stdin` uses the same authored
input boundary. It assigns each envelope once to one transport in round-robin
order, keeps the existing authenticated origin and TLS/size bounds, and performs
no provider replay. Different envelopes and network conditions can confound
transport comparison; the output is not a matched same-task performance claim.

`quattro-agent native probe --decision-stdin` similarly requires one bounded
authored envelope. Missing authoring performs no provider, retrieval or RTK
activity. Supply only abstract, minimally disclosed content through the private
input channel and do not retain raw stdin in logs or reports.

## Retired historical evidence

Earlier routing simulation, shadow/fusion, wait-budget, continuation, milestone
and fixed-recovery artifacts under `benchmarks/` remain historical measurements.
Their old CLI case menus and command lines are unsupported. Those records do
not measure the current v2 implementation and cannot establish native adoption,
useful offloads, task success, latency improvement or deployment readiness.

Current acceptance requires actual supported native execution, distinct model-
authored decisions, validated provider responses and honest delivery/application
evidence. Fixtures and configuration remain separate from those results.
