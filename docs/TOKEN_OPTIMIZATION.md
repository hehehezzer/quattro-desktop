# Token optimization ownership

Quattro owns every optimization that can change the information available to
the model: history selection/summarization, retrieval and repository context
selection, semantic pruning, tool selection, reasoning effort, and context,
conversation, and retrieval budgets. These decisions are fixed in the locked
`ExecutionPlan` before dispatch.

OmniRoute may perform only semantics-preserving gateway optimization in
passthrough mode: provider-native prompt caching, stable-prefix reuse, exact
prompt-block/tool-schema deduplication, serialization, connection reuse,
same-target transport retry, streaming, and usage accounting. It must not
summarize, prune, select tools, alter effort/budgets, or change the target.

When supplied by the provider, Quattro reports total input, cached input,
uncached input, output tokens, and cache hit rate with
`cacheMetricSource=provider_reported`. If cache accounting is absent or
inconsistent, cached/uncached/hit-rate values remain unavailable; savings are
never fabricated.
