# Benchmarks

## Jev runtime milestone continuation

`jev-pr31-milestone-summary.json` indexes the final source-matched task matrix,
real managed Codex/standalone Pi probes, and per-decision latency measurements.
See [runtime milestone methodology](../docs/JEV_RUNTIME_MILESTONES.md).
Automatic validation ordering remains opt-in and unsuitable for production:
zero useful live offloads and zero avoided agent reasoning were demonstrated.
The earlier non-`final` milestone artifacts are pre-repair exploratory history,
not evidence for the current source. Component calls are never counted as
runtime interception, nor are aggregate ON differences causal speedup claims.

## Retrieval benchmark

The benchmark runner accepts a JSON document containing synthetic or otherwise
public cases. Do not add private prompts, conversation history, local absolute
paths, memory notes, credentials, or generated result databases.

Run the public sample from a checkout:

```bash
PYTHONPATH=src ./src/quattro-agent retrieval benchmark \
  --directory . \
  --dataset benchmarks/sample.json
```

`src/quattro_agent/benchmark.py` reports routing accuracy, retrieval ranks,
latency, context budget, and isolation failures. Use a separate ignored output
path for result JSON when comparing revisions.
