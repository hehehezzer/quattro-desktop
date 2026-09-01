# Quattro Operations

## Normal checks

```text
quattro-agent status --json
quattro-agent doctor --json
quattro-agent deployment status
quattro-agent config validate
```

For the shell, restart only through the supported helper and then inspect the
log, IPC targets, and process count:

```text
~/.local/bin/restart-quickshell
cat /tmp/quickshell.log
qs ipc show
pgrep -a quickshell
```

## Accounts and routing

Codex accounts remain isolated under their individual `CODEX_HOME` paths. Both
must use the approved credential-free loopback OmniRoute Responses provider and
one shared model catalog. Do not copy `auth.json`, tokens, or account config
between homes.

Before Codex execution, Quattro validates the account provider contract and,
when the source checkout is available, validates that the tracked model catalog
matches the active shared catalog. A mismatch is a release error: deploy the
reviewed catalog through the normal release procedure, then retry.

## Runtime release checks

The source dashboard exposes display-safe runtime fields: source revision,
manifest revision, manifest parity, active catalog SHA-256, and active account.
A false manifest-parity result means the installed runtime is not the current
source release; do not make ad-hoc broad copies from a dirty worktree.

## Known incidents and responses

### Stale OmniRoute catalog

A source catalog may contain required auto routes while the active shared copy
is older. The Codex preflight now fails clearly. Validate the active catalog,
release the reviewed catalog artifact, and re-run account contract validation.

### Source/runtime drift

A deployment manifest records source/deployed hashes. If it is stale or false,
review and commit the intended source changes, build the normal release, verify
parity, then activate it. Do not rely on a catalog-only repair as a substitute
for a full release.

### Context budget truncation

Live state must use compact task/session projections. Full durable metadata can
exceed context budgets and hide structured fields. Keep only status-relevant
fields in live retrieval projections.

### Pi writable work

Pi writes are intentionally unavailable until the runtime can enforce an
isolated writable workspace with network disabled. See
[PI_WRITABLE_POLICY_DESIGN.md](PI_WRITABLE_POLICY_DESIGN.md).
