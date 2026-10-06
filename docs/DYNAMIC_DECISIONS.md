# Model-authored development decisions

The native execution model authors the current question, alternative identifiers,
descriptions, and relevant scalar parameters. `operational_decision` sends a
bounded `quattro-jev-decisions-v2` envelope to the existing TypeSafe System One
route. There is no development-category or question menu in this protocol.
Different decisions may have completely different alternatives and parameters.

Call `decision_capabilities` first to observe the current integration. A model
can then ask about using a tool, whether RTK supports that command family,
gathering missing evidence, choosing verification order, recovering after a
failure, or the next useful step. The native Pi extension reminds the model to
author a fresh decision after meaningful changes in evidence. Codex exposes the
same typed tool contract; its native MCP interface has no automatic tool
interception boundary.

Each option contains an arbitrary identifier and description, plus a host
effect describing how its advice can be interpreted. Effects are integration
boundaries, not a question vocabulary. Tool-dependent effects require a named
capability confirmed by the host. Model-supplied booleans and option descriptions
cannot create tools, allow network access, expand retrieval scope, bypass owner
approval, authorize retries, select accounts/models, or prove task completion.
Exactly one option defers to agent reasoning; its identifier is model-authored.

## Transport and confidentiality

The [official TypeSafe OpenAPI schema](https://api.typesafe.ai/openapi.json)
allows named choice questions with arbitrary criterion
identifiers and descriptions. The client keeps the fixed approved HTTPS origin
and existing authenticated `jev-latest` route; GPT-6.1 Sol High authors decisions
when selected in the native host. Jev evaluates the authored choices. No new
credential grant or provider is introduced.

Author an abstract decision, not a copy of a task or transcript. The envelope
must not contain commands, source code, paths, URLs, tool output, credentials,
raw prompts, or responses. Context accepts bounded scalar parameters. Validation
rejects unknown fields, invalid identifiers, forbidden content shapes, excessive
payloads, duplicate keys, unsupported effects, and capability mismatches. Content
shape checks are defense in depth; they do not make arbitrary private text safe
to send. The host remains responsible for minimal disclosure.

The provider response must match the exact authored option identifiers, finite
confidence and normalized probabilities, expected answer type, approved model
identity, and bounded usage. Advice below the existing 0.90 confidence floor,
agent fallback, unavailable capabilities, malformed responses, or provider
failure returns control to native reasoning. The system never retries an
ambiguous provider POST. Session deadlines, single-flight ownership, worker
capacity, cooldown, and a finite 64-attempt session budget remain enforced.

Cache identity includes the complete question, option descriptions and effects,
parameters, state, restrictions, and trusted capability observations. Native
transport revisions are monotonic; changing evidence or capabilities invalidates
prior advice. Persistent telemetry records stages, counts, bounds and sanitized
provenance, rather than authored questions, context, or raw provider bodies.

## Breaking change and migration

Only `quattro-jev-decisions-v2` is accepted. The v1 routing and operational
questionnaires, category menus, and feature-based provider handlers are removed.
Legacy envelopes fail validation before credential lookup or provider I/O. They
are not translated into invented questions. Callers must obtain an authored v2
envelope from their execution model and preserve the host capability boundary.

`JevClient.evaluate` accepts a validated decision mapping. Text feature projections
and legacy dictionaries are no longer supported. `validate_response` requires
an explicit mapping of the authored criteria. Native settings no longer choose
decision categories; legacy category settings are ignored with a status notice.

The initial immutable execution plan still enforces explicit targets, registry
availability, and deterministic host limits. Operational questions are authored
inside native execution, after the model can inspect current evidence. The
bootstrap does not contact Jev or synthesize a question.

Use `quattro-agent native probe --decision-stdin` to provide an authored envelope
through bounded private stdin. Without one, the diagnostic reports that native
authorship is required and performs no provider, retrieval, or RTK activity.
Live transport diagnostics likewise require explicit authored decisions. There
is no built-in diagnostic question or option menu. Do not retain supplied
questions, provider bodies, prompts, or responses in reports.

Legacy preflight, retrieval, repeated-failure and validation guards continue to
enforce independent host restrictions and bounded progress without remote
questionnaires. A failed bounded test is returned to the native execution model,
which can inspect evidence and author the next decision. No hidden fixed retry
question, automatic provider replay, or successful-task claim is introduced.

## Deployment and evidence

`scripts/deploy_dynamic_native.py` previews an ordinary native helper rollout;
`--apply` updates the existing helper commands and registered Pi extension with
backups. It creates a hash-verified dependency bundle, including the separately
launched Jev worker, and checks imports and standalone startup without a provider
request. Execution writes no bytecode into the bundle. Installed retrieval and
repository-metadata hardening is preserved.

Protected harness packages have independent code, extension and policy pins.
Their migration must be reviewed as one concrete cutover without changing
application code, allowed roots, operations, route constraints or credentials.
A changed policy digest invalidates existing grants. Coordinate sessions first,
retain provenance, and use fresh grants through the existing authority mechanism.
A code review or broad task approval does not itself authorize a protected pin
change. Do not restart a running user session merely to claim deployment.

Provider response validation, advice acceptance, native delivery and actual
application are separate evidence. Uncertain advice returns control to native
reasoning under the unchanged confidence floor. A successful native fallback
action does not prove accepted Jev advice. Fixture success and configuration do
not prove real native host adoption; report live results and remaining blockers
separately. Static menus limited expressiveness, but that alone does not establish
the cause of historical failures.
