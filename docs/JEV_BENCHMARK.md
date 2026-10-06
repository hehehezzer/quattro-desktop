# Jev diagnostics and retired routing benchmarks

Current diagnostics require the
[model-authored v2 contract](DYNAMIC_DECISIONS.md). No benchmark supplies a
built-in task category, question, option list or feature questionnaire.

`scripts/benchmark_jev.py` is retired and exits with a retired status without
provider access. Its former simulated routing benchmark cannot be used as
current provider, native adoption or speedup evidence.

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
