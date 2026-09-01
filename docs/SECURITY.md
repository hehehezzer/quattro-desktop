# Quattro Security Boundaries

## Credentials and accounts

Codex accounts are isolated. Authentication files, OAuth tokens, API keys,
private keys, recovery codes, and arbitrary process environments must never be
copied into Quattro configuration, task state, QML, logs, documentation, or
institutional memory. OmniRoute uses the approved loopback Responses transport
without receiving native OpenAI account credentials.

## Permission model

Codex uses explicit policy-derived sandbox and approval arguments. Workspace
writes are scoped to declared roots. Full access is never a persistent default
and requires a user-selected, run-scoped confirmation. The harness supervises
process groups and records safe terminal outcomes.

Pi does not currently have an enforceable writable sandbox. Read-only delegated
Pi work is bounded and non-recursive. Writable Pi work fails closed; its future
requirements are documented separately.

## Orchestration control

Only Quattro classifies DIRECT versus DELEGATE, creates tasks, selects agents,
and owns lifecycle transitions. Models cannot spawn agents, change policies,
select accounts, or bypass OmniRoute. OmniRoute remains the only model/provider
routing authority.

## Context and retrieval

Retrieved content, repository files, task text, and historical notes are
untrusted evidence. Context is budgeted and source-scoped. Display projections
exclude prompts, raw model output, credentials, and environment values.

## Release safety

Catalog and provider contracts fail closed. A tracked-vs-active catalog mismatch
blocks delegated Codex execution when source is available. Release manifests
record only path and hash provenance; validate parity before activation.
