# Routing

Quattro separates model selection, local task tier, and reasoning effort.

| Tier | Default effort | Automatic route label |
| --- | --- | --- |
| FAST | low | `auto/coding:cheap` |
| STANDARD | medium | `auto/coding` |
| REASONING | high | `auto/reasoning` |

The classifier is deterministic and local. When the selected model is exactly
`auto`, Quattro passes the tier's route label to OmniRoute. A concrete model or
route selected by the user is preserved. The managed task's effective effort
still comes from Quattro's tier policy.

OmniRoute is the authority for provider/account selection, capability gates,
health, rate limits, cost, cooldowns, and fallback. Quattro validates only the
credential-free loopback contract and the required catalog labels; it does not
duplicate gateway internals.

Escalation is bounded: FAST → STANDARD → REASONING, with at most one configured
exceptional effort after evidence of unresolved ambiguity or architecture risk.
