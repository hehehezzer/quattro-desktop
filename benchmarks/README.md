# Retrieval benchmark

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
