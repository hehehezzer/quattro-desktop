# Quattro Evidence-Aware Request Routing

Routing policy: `quattro-routing-v2`

Benchmark normalization: `benchmark-normalization-v1`

Quattro keeps three distinct concepts separate:

1. **Model / route** — the real OmniRoute model ID selected by Codex `/model`.
2. **Routing tier** — Quattro's local `FAST`, `STANDARD`, or `REASONING` classification.
3. **Reasoning effort** — the Quattro-selected effort sent with that request.

Quattro classifies locally; it does not ask an LLM to choose a route and does
not implement provider transport, connection/account fallback, quota reset, or
billing algorithms. **OmniRoute owns final provider/model dispatch.** Quattro
owns the task requirement and quality evidence supplied to that boundary.

## Live path and ownership

The current `quattro-agent prompt` path is:

```text
CLI run_prompt
  -> DIRECT/DELEGATE decision
  -> HarnessRuntime.direct_response or HarnessRuntime.create_task
  -> routing.classify_request
  -> routing_intelligence.profile_task
  -> FAST / STANDARD / REASONING minimum requirement
  -> automatic_model_override (only when configured model == auto)
  -> Codex Responses request through the existing OmniRoute provider
  -> OmniRoute candidate eligibility, health/quota/cost ranking and dispatch
```

For delegated Codex tasks Quattro controls the `-m` route requirement and
`model_reasoning_effort`; Codex constructs the final Responses payload. When
the connected gateway advertises `routing_header_transport`, Quattro uses
Codex's documented custom-provider `env_http_headers` mechanism to carry the
same bounded routing envelope in `X-Quattro-Routing`. Direct responses put the
envelope in the request body. No Codex patch or model-visible instruction is
used.

## Deterministic TaskProfile

`TaskProfile` records:

- task type;
- complexity, ambiguity, risk, scope, and reasoning depth;
- verification strength;
- estimated context tokens and context class;
- hard required capabilities;
- minimum quality threshold;
- transparent signals and component scores.

Classification combines requested operation, diagnosis, architecture,
uncertainty, mutation scope, security, concurrency, database/infrastructure,
destructive potential, context, and validation strength. Keyword patterns are
bounded signals, never the sole classifier. Operation semantics take
precedence over stray nouns: a localized README rename remains FAST even if
the prose mentions authentication, while a short authorization-bypass request
is REASONING.

Tier semantics are minimum quality requirements, not model names:

| Tier | Default quality floor | Meaning |
| --- | ---: | --- |
| FAST | 0.45 | low risk, localized, strongly verifiable |
| STANDARD | 0.65 | normal bounded implementation/debugging |
| REASONING | 0.80 | architecture, security, concurrency, migration, system scope, high ambiguity, or weak validation |

The floors, evidence weights, preference mode, and outcome sample threshold are
validated configuration. Default evidence weights
are metadata `0.25`, public benchmarks `0.50`, and local validated outcomes
`0.25`. Missing evidence is omitted and remaining weights are renormalized;
unknown evidence never receives an optimistic quality value.

## Three evidence domains

1. **OmniRoute runtime/model metadata** is authoritative for hard capabilities,
   practical context, modality, tool compatibility, price, health, quota,
   rate limits, and cooldown. Missing fields fail conservatively where safe.
2. **Curated public benchmark evidence** provides cold-start quality dimensions
   for coding, repository work, reasoning, agentic tool use, long context, and
   instruction following.
3. **Quattro local outcomes** provide privacy-safe aggregate validated success,
   retries, escalation, latency, and cost by task class/tier/provider/model.

Candidate evaluation is lexicographic:

```text
capability -> practical context -> availability -> quality floor
           -> expected completion cost -> latency -> stable identity
```

Cost cannot compensate for a missing capability, insufficient context,
unavailability, or a quality estimate below the task floor. Expected completion
cost includes a bounded geometric retry estimate and escalation reserve rather
than comparing raw input-token price alone.

## Benchmark cache and refresh

The private cache is
`$QUATTRO_STATE_DIR/private/routing/benchmark-cache.json`. Records are strict,
size/count bounded, provenance-bearing, and accepted only from allowlisted
SWE-bench, LiveCodeBench, TerminalBench, or official provider/model-card HTTPS
hosts. Scores must already be normalized independently into `[0,1]` dimensions;
raw unrelated benchmark scales are never directly compared. Exact model and
variant matches retain confidence; family/variant mismatch is discounted and
age decays confidence. Downloaded data is parsed as inert JSON and never
executed.

Quattro ships three exact-identity cold-start records from the official Codex
model card for GPT-5.6 Sol, Terra, and Luna. The raw 5/5, 4/5, and 3/5
capability-icon ratings are normalized mechanically to coding scores 1.0, 0.8,
and 0.6 with reduced confidence; they are not presented as SWE-bench results.
On first adaptive use the private cache is seeded atomically when empty.

Further refresh is out of band and never runs on the request hot path:

```text
quattro-agent routing refresh-evidence --input curated-cache.json
quattro-agent routing refresh-evidence --url https://ALLOWLISTED/cache.json
```

Refresh has a 10-second network timeout, 2 MiB limit, atomic replacement, and
last-known-good failure behavior. Normal routing is fully offline.

## Local validated outcomes

The private aggregate store is
`$QUATTRO_STATE_DIR/private/routing/local-outcomes.json`. It contains no prompt,
response, source code, tool body, environment, credential, or account secret.
Execution success and validated success are separate. Automatic harness
validation records pass/fail/not-run against the effective OmniRoute route;
operators can import a richer provider/model observation when available:

```text
quattro-agent routing record-outcome \
  --provider PROVIDER --model MODEL --task-type implementation --tier STANDARD \
  --execution-success --validated passed --latency-ms 1200 --cost 0.002
```

Local influence grows linearly to full confidence at 20 validated samples. A
single success cannot establish model quality.

## Explainability and deterministic replay

Every new managed dispatch stores a sanitized snapshot in private task state:
TaskProfile, route, policy/normalization versions, evidence content versions,
configured model, and (when available) candidate decisions/rejections. No raw
prompt is copied into the snapshot.

```text
quattro-agent routing profile --prompt "..." --pretty
quattro-agent routing explain --task TASK_OR_SESSION --pretty
quattro-agent routing replay TASK_OR_SESSION
quattro-agent routing status
```

Replay refuses an unsupported policy version and reproduces route selection
from the persisted TaskProfile and configured-model precedence. It does not
invent current health state.

`python scripts/routing/evaluate.py` runs the fixed offline before/after policy
corpus. It reports fixture accuracy, under/over-routing, tier-cost and bounded
completion-cost proxies, and escalation need. It explicitly labels real
provider cost, validated production success, provider concentration, and load
latency as not measured rather than fabricating those values.

## Standard and adaptive compatibility

Quattro negotiates `GET /api/v1/capabilities` with a five-minute cache. A
standard upstream-compatible OmniRoute that lacks the enhanced endpoint stays
healthy and uses the existing FAST/STANDARD/REASONING tier routes. A
Quattro-compatible OmniRoute adds a five-second runtime candidate snapshot,
hard capability/context requirements, ordered preferences, runtime fallback,
and sanitized routing receipts. Candidate metadata failure records
`adaptive_routing_unavailable` and falls back to standard tier routing.

In adaptive mode Quattro reads only the public candidate API. It never reads
provider configuration, accounts, or credentials. The routing envelope contains
only schema version, hard capabilities, minimum context, ordered candidate IDs,
balanced preference mode, TaskProfile ID, and policy version. OmniRoute expands
automatic tier aliases to the full eligible auto inventory only for a validated
enhanced envelope, revalidates all hard/runtime gates at dispatch, strips the
extension before provider translation, and records a bounded metadata-only
receipt for exact delegated-task correlation.

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
