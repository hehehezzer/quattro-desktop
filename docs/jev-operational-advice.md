# Operational safety and model-authored advice

Substantive development decisions use the
[v2 model-authored interface](DYNAMIC_DECISIONS.md). The execution model creates
the current question, alternatives and relevant abstract parameters. Legacy
preflight, retrieval, task and repeated-result hooks remain deterministic host
guards; they do not construct questionnaires or call Jev.

## Existing guard coverage

Direct Codex exposes `operational_guard` as an explicit MCP tool. This boundary
does not automatically intercept all native tools. Pi uses supported tool-call
and tool-result boundaries for its existing guard integration. Managed execution
preserves its separate host policy and control plane.

When the existing guard setting is enabled, host denial stops an operation.
Sensitive or destructive work still requires the appropriate owner approval.
Opaque actions remain conservative. An approval assertion, retrieved text or
provider option cannot manufacture permission. Exact existing read-only RTK
inspection vectors retain their bounded host classification; other command
arrays remain subject to the existing gate.

The retrieval guard can reject disallowed scope or stop when explicit local
sufficiency evidence was supplied. Otherwise the existing bounded query/scope
continues. The retrieval engine enforces sources and budgets. No provider
creates a query, refines private evidence or enlarges retrieval scope here.

Repeated failure/unchanged-result fingerprints stay in bounded local session
memory. After repeated no-progress observations, the guard requests a changed
plan; further identical repetition can require owner attention. Success clears
the tracked observation. This never automatically retries a tool or contacts
Jev. The executing model may author a new decision after inspecting the failure.

## Authority and deployment

Risk fields and fixed guard thresholds enforce host safety. They are independent
of the model-authored question and choice content. Native model/account choices,
owner grants, allowed roots, network policy, retry bounds, mandatory validation
and completion remain host responsibilities.

Keep existing explicit activation settings and protected policy/code pins
unchanged unless their concrete migration is reviewed and authorized through the
existing mechanism. New helper code alone is not permission for new persistent
hooks, retrieval origins, remote access or worker grants. Coordinate running
sessions before any supported reload.

Guard telemetry is marked as local instrumentation with no provider consultation.
Provider attempt, accepted advice and actual application are recorded separately
for `operational_decision`. No raw prompt, output, path, fingerprint or provider
body becomes remote decision content or persistent advice evidence.

The previous fixed-category operational advice implementation and its activation
examples are retired. Static menus limited expressiveness; that fact alone does
not identify the cause of historical provider or execution failures.
