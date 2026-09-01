# Quattro Tiered Request Routing

Quattro keeps three distinct concepts separate:

1. **Model / route** — the real OmniRoute model ID selected by Codex `/model`.
2. **Routing tier** — Quattro's local `FAST`, `STANDARD`, or `REASONING` classification.
3. **Reasoning effort** — the Quattro-selected effort sent with that request.

Quattro classifies locally; it does not ask an LLM to choose a route and does
not implement provider, connection/account, quota, reset-window, fallback, or
billing algorithms. **OmniRoute owns those decisions.**

Quattro, not the native Codex session, owns effective reasoning effort for
Quattro-managed execution. A parent Codex UI may display `auto medium`, or the
user may select `xhigh` through `/model`; that displayed/default effort is not
used for the managed child request. Quattro injects the effective value with
`-c model_reasoning_effort="<tier effort>"` on every Codex dispatch. Task
metadata and `routing.dispatched` are the source of truth.

For example, `auto medium` in the parent can execute a file lookup as
`FAST / auto/coding:cheap / low`. Conversely, a native `low` default executes a
race/deadlock investigation as `REASONING / auto/reasoning / high`.

## Verified effort values

The installed Codex catalog advertises these effort values for the supported
GPT-5.6 routes:

```text
low, medium, high, xhigh, max, ultra
```

`FAST`, `STANDARD`, and normal `REASONING` deliberately use only `low`,
`medium`, and `high`. `ultra` is available only after a strictly bounded,
evidence-gated exceptional escalation. OmniRoute's Codex Responses translator
maps client-side `ultra` to wire-level `max`, so `ultra` is never the normal
default.

## Automatic `/model` behavior

When the selected Codex model is exactly `auto`, Quattro maps the local tier to
existing, live OmniRoute auto-combo routes:

| Tier | Requested OmniRoute route | Requirement profile | Effort |
| --- | --- | --- | --- |
| `FAST` | `auto/coding:cheap` | low-cost coding capability with low-latency tie breaking | `low` |
| `STANDARD` | `auto/coding` | normal coding capability | `medium` |
| `REASONING` | `auto/reasoning` | verified reasoning capability | `high` |

Those routes are selected with Codex's standard `-m` model argument. They are
requirements, not fixed-model aliases. OmniRoute first removes candidates that
are circuit-open, rate-limited, unavailable, cooling down, quota-exhausted,
session-unavailable, repeatedly failing, context-incompatible, or below the
task capability floor. A half-open breaker candidate remains eligible only as
an explicit health-system recovery probe.

Among the surviving capable candidates, OmniRoute orders by incremental model
cost first. Latency, observed reliability, and the existing multi-factor score
break equal-cost ties; model size, account tier, `pro`, `xhigh`, `thinking`, and
similar labels are not selection authority. Coding and reasoning pools use the
existing capability/intelligence registry and observed task-fitness sources.
A name-only wildcard boost cannot establish coding capability.

Fallbacks remain inside the same eligible/capable pool. Equivalent targets that
share a connection/provider failure domain are still suppressed by OmniRoute's
existing exhausted-connection/provider tracking after a failure. When a
cooldown expires and the health record clears, the cheaper candidate naturally
becomes eligible again on the next dispatch.

## Manual `/model` behavior and precedence

A concrete `/model` choice is always respected. Only the model/route portion is
preserved; native reasoning effort is still replaced. If Codex's selected model is
anything other than exactly `auto` (for example an account-pinned GPT-5.6
route or `auto/coding` explicitly chosen by the user), Quattro does not
replace it. It only sends the automatically selected reasoning effort.

The shared Codex model catalog is the single picker/direct-selection registry.
It publishes these Quattro route modes first, followed by the verified manual
OmniRoute models:

```text
auto
auto/coding:cheap
auto/coding
auto/reasoning
```

Selecting `auto` enables per-task adaptive routing. Selecting one of the three
`auto/...` values pins that exact OmniRoute route for later managed requests.
Unknown values are rejected by Codex against the same catalog instead of being
silently converted to `auto`. The catalog is deployed from
`src/quattro/omniroute-model-catalog.json`; Quattro preflight fails closed if a
required route is missing.

Precedence is therefore:

```text
Explicit user model/route choice
        ↓
Automatic FAST / STANDARD / REASONING classification
        ↓
Tier-selected reasoning effort
        ↓
OmniRoute provider/account/quota/cost/fallback behavior for that route
```

Resume preserves the native session's model; Quattro does not force a new
model route on resume. Task metadata and `routing.dispatched` events expose
`selectedModel`, `effectiveModelRoute`, the backward-compatible `modelRoute`,
`modelSelection` (`automatic` or `manual`), routing tier, and effort without
recording prompt content or credentials. Native Codex's compact status line
continues to show the effective route, effective effort, and working directory.

There is intentionally no `/routing` command: automatic classification plus
`/model` is sufficient, and a manual tier override would add command/UI state
without a demonstrated operational need.

## Escalation

Tier escalation is bounded:

```text
FAST / low → STANDARD / medium → REASONING / high
```

A single failed command or test never escalates. Retry requires at least two
attempts plus bounded evidence of ambiguity, security/architecture risk, a
race/deadlock, or interacting failures. `REASONING / high` may make one
additional exceptional escalation to the configured `ultra` effort only with
such unresolved evidence. No further automatic transition is possible.

## Context efficiency

Tier selection works independently of the existing deterministic retrieval
router. Quattro continues to inject only bounded relevant retrieval and
mandatory-policy context; it adds neither a second RAG index nor a new gateway.
