# Jev decision plane

See [Model-authored development decisions](DYNAMIC_DECISIONS.md) for the
canonical v2-only contract and migration requirements. The native execution
model authors the actual question and alternatives after inspecting current
evidence. No host category table supplies development questions or choices.

`DecisionSession` owns one supervised, bounded provider worker for a session.
It preserves single-flight admission, wall deadlines, finite request budgets,
cancellation, worker cleanup and failure cooldown. Jev evaluates only validated
abstract envelopes at the existing authenticated TypeSafe endpoint. It neither
executes actions nor selects the execution model.

The public typed transport has bounded questions, descriptions and scalar
context, two to eight distinct alternatives, and exactly one semantic fallback
with effect `agent`. Its option identifier is authored by the model. Safety
effects map advice to independent restrictions; they do not prescribe the
question or enumerate development alternatives.

Host capability observations are supplied outside the public envelope. A
capability-dependent alternative must reference an observed capability. Model
assertions cannot grant tools, network access, retrieval scope, retries or
permissions. The complete envelope and trusted capability observations bind
cache identity; changed evidence invalidates prior advice.

## Native boundaries

Pi's supported pre-agent boundary supplies the host capability snapshot and
instructions to author decisions at meaningful planning, tool/RTK, context,
verification, recovery and next-action milestones. Its optional existing result
checkpoint setting supplies changed-evidence reminders, without constructing a
provider question. The model calls `operational_decision` with its own envelope.

Direct Codex exposes the same canonical schema through MCP. This boundary is a
model-selectable tool, not a claim that every native turn or tool call is
intercepted. Managed execution uses its existing private session gate; where
that gate lacks an attested execution-tool inventory, capability discovery
returns an empty capability map rather than claiming another MCP's tools.

Existing safety/progress guards remain local. Required host validation runs
all existing checks in their original order. The bounded test tool executes
one invocation and returns failure for native reasoning. Neither boundary
constructs an implicit Jev question or retries a provider request.

## Evidence

Provider attempt, response validation, accepted advice, delivery and application
are different stages. A cache hit is not a new provider call. Pi can confirm
supported tool-result delivery; internal model reliance remains unknown.
Unobserved application remains unverified. Persistent telemetry excludes
questions, descriptions, authored identifiers/context, prompts and provider
bodies. Configuration and fixture success do not prove real adoption.

Earlier fixed-taxonomy decision-plane, continuation and milestone measurements
are retired. Their aggregate artifacts remain historical records under
`benchmarks/`; they do not describe the current executable API.
