# Durable OMP execution boundary

OMP is a distinct durable agent identity. Existing Pi and Codex tasks, runs,
logical sessions, checkpoints, events and leases retain their original identity.
Task database schema 4 atomically rebuilds the agent CHECK constraints and
validates foreign keys before committing. Older runtimes must not execute
against a migrated database; keep a database backup before rolling back software.

The durable OMP adapter uses the closed OMP SDK runtime, not the native CLI or
its `always-ask` launch profile. Quattro supplies a bounded private prompt,
locks `openai-codex/gpt-6.1-sol` with medium effort, and registers no host tools.
Native sessions are memory-only. Prompts and answers are passed through private
pipes; the worker does not write a native transcript. The SDK receives a fresh private
HOME with a regular-file log sentinel and disabled logger transports, so native
HTTP-error dump paths cannot persist private request data. Native OMP
authentication uses the separately explicit original agent directory. The
temporary HOME is removed after the runtime closes. The SDK child stays in
the durable supervisor's process group for cancellation and deadlines.

The caller must supply an explicitly reviewed Bun interpreter, official OMP
18.6.3 package installation, native OMP agent directory and runtime directory.
The caller supplies a trusted SHA-256 digest for the deployment manifest.
Before starting the SDK, the worker verifies the interpreter and complete
package closure against that pinned manifest. The runtime also checks the
expected package identity and the selected model. Missing pins or changed
installation contents fail closed.
Authentication remains owned by the native OMP SDK. Python does not read, copy
or migrate Pi/Codex/OMP authentication data. A missing installation, unavailable
native provider, protocol failure or model fallback fails closed.

Fresh context-only prompt execution is supported. Native resume, interactive
execution and all writable policies are rejected. There is no native CLI
fallback and no automatic approval response. `audit-read-only` therefore keeps
the existing bounded-context/no-agent-tools execution guarantee. Network policy
here describes the unavailable tool execution surface; model transport remains
the authorized provider connection.

`workspace-write` and full-access tasks require a separately reviewed Quattro
host tool boundary before OMP can execute them. Approval dialogs alone cannot
restrict filesystem roots or network access. The scheduler reserves OMP
capacity and exact session writer identities, but those leases do not grant
permission or establish native recovery support.

Regression coverage in `tests/test_durable_omp.py` verifies retained legacy
history, foreign keys, atomic rollback, OMP capacity/session locks, strict
selection, private prompt transport, rejected capabilities and closure of the
context runtime on failure. Full repository checks remain the completion gate.
