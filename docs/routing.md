# Routing

Quattro separates task classification, exact target selection, local task tier,
and reasoning effort.

| Tier | Default effort | Legacy auto alias (compatibility only) |
| --- | --- | --- |
| FAST | low | `auto/coding:cheap` |
| STANDARD | medium | `auto/coding` |
| REASONING | high | `auto/reasoning` |

The classifier and target registry are deterministic and local. In the default
`OMNIROUTE_ROUTING_MODE=passthrough` path, Quattro resolves `auto` and the
legacy aliases to an account-qualified provider/model target, then emits a
locked `ExecutionPlan`. A concrete account-qualified route selected by the
user is preserved. The managed task's effective effort still comes from
Quattro's tier policy.

OmniRoute is the gateway for protocol normalization, provider-native caching,
exact deduplication, transport, usage accounting, streaming, and health
signals. It does not choose a provider, account, model, effort, context, or
fallback for a locked plan. `OMNIROUTE_ROUTING_MODE=legacy` remains an
explicit migration path for callers that still depend on OmniRoute's old
automatic routing engine.

Escalation is bounded: FAST → STANDARD → REASONING, with at most one configured
exceptional effort after evidence of unresolved ambiguity or architecture risk.
