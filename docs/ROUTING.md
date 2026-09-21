# Quattro Evidence-Aware Request Routing

Routing policy: `quattro-routing-v2`

Benchmark normalization: `benchmark-normalization-v1`

Quattro keeps three distinct concepts separate:

1. **Execution target** — Quattro's provider/account/model route.
2. **Routing tier** — Quattro's local `FAST`, `STANDARD`, or `REASONING` classification.
3. **Reasoning effort** — the Quattro-selected effort sent with that request.

Quattro classifies and selects locally; it does not ask an LLM to choose a
route. **Quattro owns provider, safe account alias, model, and fallback order.**
OmniRoute owns transport, provider protocol adaptation, caching, token
optimization, and runtime health signals. The default registry is
`quattro_agent/data/model-policy.json`; `QUATTRO_MODEL_POLICY` may point to a
validated private override. Neither file contains credentials.

## Live path and ownership

The current `quattro-agent prompt` path is:

```text
CLI run_prompt
  -> DIRECT/DELEGATE decision
  -> Quattro request boundary (latest request + bounded task/session facts)
  -> PreRoutingInput
  -> existing routing_intelligence.profile_task classifier
  -> FAST / STANDARD / REASONING + quality floor
  -> validated model registry + deterministic exact target/fallback ordering
  -> durable task/envelope persistence
  -> Codex execution preparation (bootstrap, tools, skills, permissions, AGENTS, history)
  -> final_request_tokens context-capacity eligibility only
  -> OmniRoute exact-route transport and provider dispatch
```

The request-boundary step is the single task-intelligence authority. It runs
before `HarnessRuntime._agent_plan` assembles Quattro-owned retrieval and policy
context and before the Codex child/session can construct its native Responses
request. The persisted envelope is bounded metadata, not a serialized
conversation. A legacy task without an envelope may use a one-time compatibility
recovery path; new tasks never rank candidates after execution preparation.

The phase ownership is explicit:

```text
PRE_ROUTING
  user request -> TaskProfile -> tier/quality floor -> exact target + fallbacks
EXECUTION_PREPARATION
  Quattro context gates -> Codex-owned bootstrap and final request assembly
FINAL_ELIGIBILITY
  final request size -> context fit only; no tier/quality reclassification
DISPATCH / VALIDATION
  OmniRoute actual target/usage -> fidelity check -> Quattro outcome evidence
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
- task-context, protocol-overhead, and final-request token estimates;
- context class and the selected bounded context profile;
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

## Routing context semantics

Task difficulty and request size are independent axes. Quattro builds a bounded
`PreRoutingInput` and derives `RoutingTaskInput` from it using the existing
deterministic classifier; it never
profiles the expanded Codex bootstrap, skill catalog, permission inventory,
AGENTS content, raw retrieval blobs, or previous transcript.

- `task_context_tokens` estimates the user request plus relevant conversation,
  retrieval, task-specific schemas, and output reserve.
- `protocol_overhead_tokens` estimates Quattro-owned static policy,
  coordination, and delegation instructions.
- `final_request_tokens` is their sum and remains the compatibility value
  exposed as legacy `estimated_tokens`.

Complexity, reasoning depth, and the quality floor come only from semantic
work, ambiguity, scope, risk, and verification. Protocol overhead cannot raise
those values. Final request size still adds `long_context` and is a hard
practical-context gate: a FAST request estimated at 70k rejects a 32k model but
remains FAST when a sufficiently capable 128k model is available.

Codex constructs additional system, tool, skill, sandbox, permission, AGENTS,
environment, and session bootstrap context after Quattro launches it. Quattro
does not read or duplicate that private request. Consequently diagnostics mark
runtime-owned overhead as unmeasured; OmniRoute's final request pipeline remains
authoritative for actual wire-size compatibility. A large protocol overhead can
reject a candidate for context capacity, but cannot increase complexity,
reasoning depth, quality floor, or tier.

## Context gating

Quattro uses five coarse profiles rather than task-specific prompt templates:

| Profile | Quattro-owned optional context |
| --- | --- |
| `CHAT_MINIMAL` | memory policy and mandatory operational policy only |
| `CODE_SIMPLE` | bounded retrieval plus delegation policy |
| `REPOSITORY_EXECUTION` | bounded retrieval; coordination only for mutation; delegation policy |
| `SECURITY_REVIEW` | bounded relevant retrieval and delegation policy |
| `DESIGN` | bounded relevant retrieval and vision requirement |

The compact memory trust/storage policy and mandatory workspace rule remain
always loaded. Memory *content* remains gated through bounded retrieval.
Detailed cooperative-session context is omitted only when the task has no
repository-write capability; mutation tasks retain conflict prevention and
write-scope instructions. Quattro never loads Codex skill bodies, permission
prefix inventories, or generated AGENTS instructions itself, so those remain
Codex/runtime-owned and must use Codex-supported lazy loading and tool-side
enforcement rather than binary patches.

`context.assembled` records counts and categories, never raw private context.
Run `python scripts/routing/measure_context.py` for content-free synthetic
before/after measurements of the Quattro-owned portion.

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
           -> expected completion cost -> normal effort tie-break -> latency
           -> stable identity
```

Cost cannot compensate for a missing capability, insufficient context,
unavailability, or a quality estimate below the task floor. Expected completion
cost includes a bounded geometric retry estimate and escalation reserve rather
than comparing raw input-token price alone.

When OmniRoute exposes the same model at multiple reasoning-effort suffixes,
the effort suffix is normalized back to the base model for benchmark evidence
(`gpt-5.6-luna-high` uses the `gpt-5.6-luna` evidence). Product variants such
as `lite`, `mini`, or `web` remain separate. Cost remains the first ordering
key; an equal-cost tie is resolved toward the task's lower normal effort so a
FAST request cannot be promoted to a `-high` variant merely because that ID
sorts first. The selected effort is retained in the sanitized candidate
diagnostic.

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

## Registry and runtime metadata compatibility

Quattro negotiates `GET /api/v1/capabilities` with a five-minute cache. A
standard upstream-compatible OmniRoute can still transport a validated explicit
catalog route. A Quattro-compatible OmniRoute additionally provides a five-second
sanitized runtime candidate snapshot and routing receipts. These are health and
evidence inputs; they are not model-selection authority.

In adaptive mode Quattro reads only the public candidate API at PRE_ROUTING. It never reads
provider configuration or credentials. The model policy contains only safe
provider/account/model aliases and capability metadata. Every target is checked
against the approved catalog. Account-qualified routes are single-target combos,
so cache lookup, translation, and token optimization remain in OmniRoute without
allowing it to widen the target set.

Quattro selects the lowest configured cost rank that satisfies capability,
context, tier, and availability evidence, preferring the requested account only
after cost. The remaining eligible targets form the bounded fallback chain.
Unknown capability or context facts do not receive optimistic defaults.

Except for the explicit Astra choices described below, Quattro owns effective
reasoning effort for Quattro-managed execution. A parent Codex UI may display `auto medium`, or the
user may select `xhigh` through `/model`; that displayed/default effort is not
used for the managed child request. Quattro injects the effective value with
`-c model_reasoning_effort="<tier effort>"` on every Codex dispatch. Task
metadata and `routing.dispatched` are the source of truth.

The effort provenance is therefore: `classify_request` selects the tier,
`effective_reasoning_effort` maps the tier to `low`/`medium`/`high`, and
`HarnessRuntime._agent_plan` injects that value into the Codex command before
the child starts. Codex serializes it into the Responses request; OmniRoute's
Responses translator preserves the explicit effort and its provider adapters
may only perform provider-specific normalization or a capability-safe clamp.
The optional context-size classifier does not write reasoning effort. The
previous `medium` → `high` observation was consequently not evidence that a
large prompt should raise task intelligence; it must be diagnosed at the
Codex/provider adapter boundary if reproduced. Current regression coverage
asserts native defaults cannot override the Quattro tier and that context size
cannot change the tier.

For example, `auto medium` in the parent can execute a greeting as
`FAST / account-1 / gpt-5.6-luna / low`. Conversely, a native `low` default can
execute a race/deadlock investigation as
`REASONING / account-1 / gpt-5.6-sol / high`.

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

## Astra low/high thinking

`account-1/gpt-6-astra` and `account-2/gpt-6-astra` expose only `low` and
`high` in the shared Codex picker. Managed Astra dispatch preserves a saved
`low` or `high` choice. Unsupported saved efforts fall back to `high`.
Without a saved effort, FAST uses `low` and STANDARD/REASONING uses `high`,
including exceptional escalation. Astra launches also set Plan mode to the
same low/high effort. Other models keep their existing tier effort policy.

Each route must be provisioned as a single-target OmniRoute combo pinned to
its named Codex connection, targeting `codex/gpt-6-astra`. If the gateway's
synced catalog predates Astra, register the exact model through OmniRoute's
custom model facility and validate real Responses calls on both accounts.
A picker entry alone does not provision the gateway route.

OmniRoute must also report a current Codex client version: the local
integration was validated with `CODEX_CLIENT_VERSION=0.153.4` in the gateway's
persistent `DATA_DIR/.env`. Restart the gateway after changing that value.
An obsolete version can produce an upstream "requires a newer version of
Codex" error even when account authentication is healthy. Test both low and
high after upgrading. Do not change native account authentication stores.

## Automatic `/model` behavior

When the selected Codex model is exactly `auto`, Quattro maps the local tier to
the cheapest eligible exact target in its validated registry:

| Tier | Default family | Requirement profile | Effort |
| --- | --- | --- | --- |
| `FAST` | `gpt-5.6-luna` | low-cost verified capability | `low` |
| `STANDARD` | `gpt-5.6-terra` | balanced verified capability | `medium` |
| `REASONING` | `gpt-5.6-sol` | strongest verified reasoning capability | `high` |

The account-qualified route is passed with Codex's standard `-m` argument or
the Responses `model` field. OmniRoute may reject the route for health, quota,
or protocol reasons, but may not substitute a different model. Quattro records
the failure and advances only through its own bounded fallback chain. DIRECT
requests use structured HTTP failure status. Delegated task replay is permitted
only for read-only policies; writable tasks fail closed because free-form agent
output is not a trusted transport-failure signal and replay could duplicate
non-idempotent edits or commands.

## Manual `/model` behavior and precedence

A concrete `/model` choice is always respected. Only the model/route portion is
preserved; native reasoning effort is still replaced for other models. If Codex's selected model is
anything other than exactly `auto` (for example an account-pinned GPT-5.6
route or `auto/coding` explicitly chosen by the user), Quattro does not
replace it. It sends the automatically selected reasoning effort except for the Astra policy above.

The shared Codex model catalog is the single picker/direct-selection registry.
It publishes these Quattro route modes first, followed by the eight account-pinned
GPT-6 Astra and GPT-5.6 family routes and the currently verified Antigravity text routes:

```text
auto
auto/coding:cheap
auto/coding
auto/reasoning

account-1/gpt-6-astra
account-1/gpt-5.6-sol
account-1/gpt-5.6-terra
account-1/gpt-5.6-luna
account-2/gpt-6-astra
account-2/gpt-5.6-sol
account-2/gpt-5.6-terra
account-2/gpt-5.6-luna

antigravity/* (18 text-capable routes)
```

The eight account-qualified GPT-6/GPT-5.6 entries are single-target OmniRoute combos:
each is pinned to its named Codex OAuth account and has no cross-account
fallback. The Antigravity entries are a reviewed snapshot of the current
text-capable provider catalog, including its `no-think/` Claude variants. The
Antigravity image-only route is intentionally not a Codex picker entry; image
generation remains available through the credential-free local image MCP
bridge.

All verified account-qualified GPT-6/GPT-5.6 routes, automatic routes, and
vision-capable Antigravity text routes advertise both `text` and `image` input
modalities. Codex requires this catalog capability before it will accept a
clipboard or file image attachment. Native-vision routes receive attachments directly. Picker routes backed by
text-only models accept the attachment through OmniRoute's configured bounded
image-to-text modality bridge, so the catalog describes the effective end-to-end
input contract rather than only the upstream model's native modality.

Selecting `auto` enables per-task Quattro target selection. Selecting one of the three
`auto/...` values explicitly delegates model choice to the named OmniRoute route.
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
Quattro provider/account/model selection + bounded fallback chain
        ↓
Tier-selected reasoning effort
        ↓
OmniRoute transport/caching/protocol adaptation for the exact route
```

Resume preserves the native session's model; Quattro does not force a new
model route on resume. Task metadata and `routing.dispatched` events expose
`selectedModel`, `effectiveModelRoute`, the backward-compatible `modelRoute`,
`modelSelection` (`quattro-explicit` or `manual`), routing tier, and effort without
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

Tier selection is independent of retrieval and protocol size. Trivial chat
skips optional retrieval, coordination, and delegation text. Project work keeps
bounded relevant retrieval; repository mutations retain coordination. Static
policy blocks stay in stable order to remain cache-friendly where the provider
supports prefix caching, but Quattro does not claim a cache hit without runtime
evidence.
