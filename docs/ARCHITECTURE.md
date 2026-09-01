# Quattro Architecture

Quattro is a local desktop AI orchestration control plane. It preserves a
separation of responsibility between request orchestration, model routing, and
execution runtimes.

```text
User request
  │
  ▼
Quattro request boundary
  │
  ├── DIRECT ───► OmniRoute Responses ───► final response
  │
  └── DELEGATE ─► durable task ─► Codex or Pi ─► validation/result
```

## Responsibilities

### Quattro

Quattro classifies requests, selects an execution agent deterministically,
creates and supervises durable tasks, assembles bounded context, enforces task
policy, and projects display-safe lifecycle state. It does not choose a
provider or let a model create agents.

### OmniRoute

OmniRoute remains the authority for provider/account/model selection, cost and
quota behavior, health and context eligibility, cooldowns, and fallbacks.
Quattro supplies only request requirements through the FAST, STANDARD, and
REASONING tiers. Explicit Codex `/model` selection remains user intent.

### Codex and Pi

Codex and Pi execute tasks. Codex is the normal repository and coding runtime.
Pi is a bounded read-only delegated specialist by default. Neither runtime
owns routing, account selection, task orchestration, or durable state.

## DIRECT flow

`quattro-agent prompt` classifies a request before task creation. A DIRECT
request uses `HarnessRuntime.direct_response`, which validates the approved
OmniRoute contract, builds only bounded retrieval context, retains selected
model and tier behavior, and sends one Responses request to the loopback
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
