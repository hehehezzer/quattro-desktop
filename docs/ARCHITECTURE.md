# Quattro Architecture

## Authoritative inference boundary

The invariant is **Quattro chooses; OmniRoute executes**.

```text
Request -> Quattro Intelligence -> locked ExecutionPlan -> context compiler
        -> OmniRoute passthrough gateway -> exact provider/account/model
        -> result or structured failure -> Quattro fallback plan
```

Quattro owns classification, capability/complexity assessment, target/account
selection, reasoning effort, semantic context budgets and compilation, tools,
cross-target fallback, and routing evidence. OmniRoute owns normalization,
provider-native caching, exact deduplication, transport and same-target retry,
streaming, accounting, and health telemetry. Every authoritative plan has
`routingLocked=true`; each fallback is a new Quattro plan, never an invisible
gateway override. Legacy routing remains an explicit compatibility path.

Quattro is a local desktop AI orchestration control plane. It preserves a
separation of responsibility between request orchestration, model routing, and
execution runtimes.

```text
User request
  │
  ▼
Quattro request boundary
  │
  ▼
 PreRoutingInput → TaskProfile → FAST / STANDARD / REASONING
   │                         │
   │                         └── validated execution-target registry
   ▼
 execution preparation (Codex-owned bootstrap may now expand)
   │
   ├── DIRECT ───► exact provider/account/model route ─► OmniRoute transport ─► response
   │
   └── DELEGATE ─► durable task ─► exact provider/account/model route ─► Codex/Pi ─► result
```

## Responsibilities

### Quattro

Quattro classifies requests, selects an execution agent deterministically,
creates and supervises durable tasks, assembles bounded context, enforces task
policy, selects a validated provider/account/model execution target and bounded
fallback chain, and projects display-safe lifecycle state. Its request-boundary `TaskProfile` is the
single authority for task intelligence; native bootstrap size is not a quality
signal.

### OmniRoute

OmniRoute remains the provider transport, protocol-adaptation, caching, token
accounting, health-signal, and request-forwarding layer. Normal Quattro work
uses an account-qualified single-target route; OmniRoute must execute it or
return a failure. It does not widen an explicit route into its automatic pool.
OmniRoute-managed automatic routing remains available only when explicitly
requested. Explicit Codex `/model` selection remains user intent.

### Codex and Pi

Codex and Pi execute tasks. Codex is the normal repository and coding runtime.
Pi is a bounded read-only delegated specialist by default. Neither runtime
owns routing, account selection, task orchestration, or durable state.

## DIRECT flow

`quattro-agent prompt` classifies a request before task creation. A DIRECT
request uses `HarnessRuntime.direct_response`, which validates the approved
OmniRoute contract and model registry, builds only bounded retrieval context,
selects an exact account-qualified model route, and sends a Responses request to the loopback
OmniRoute endpoint. It creates no durable execution task and launches no
Codex/Pi child.

## DELEGATE flow

A DELEGATE request creates a task in the existing SQLite lifecycle. Quattro
records the classifier result, agent, policy, routing tier, repository
coordination state, validation status, and terminal summary. The adapter
receives bounded retrieval and mandatory context; process supervision and
validation complete the task lifecycle.

## Runtime boundaries

There is one persistent Quickshell process. The Python launcher and harness are
the control plane; QML consumes display-safe projections only. Authentication
files remain in account-isolated Codex homes and are never read into QML,
runtime state, task projections, or memory.
