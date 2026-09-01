# Quattro Cooperative Session Scheduling

Quattro admits at most five concurrent top-level sessions globally and at most
three top-level sessions for one canonical repository/project. The limits remain
configured under `cooperation` in `ai.json`:

```json
{
  "globalLimit": 5,
  "perRepositoryLimit": 3
}
```

## Shared working directory by default

A session launched in `/path/to/project` runs in exactly `/path/to/project`.
Quattro does not create a branch, checkout, or Git worktree for ordinary
sessions or their subagents, and it never switches branches automatically.
This applies equally to Git and non-Git projects.

The coordinator retains an internal `isolate=True` API for an explicitly
requested experimental worktree. Nothing in `ai.json` enables it implicitly;
ordinary CLI and harness paths pass no isolation request. Cleanup/integration
commands therefore apply only to those explicit managed worktrees. Shared-tree
sessions use ownership handoff instead of merge/cherry-pick integration.

## Canonical project identity and limits

For Git projects, Quattro resolves the absolute common Git directory and its
filesystem identity. The original tree, subdirectories, symlinks, existing
linked worktrees, and Quattro-managed worktrees share one repository ID.
Non-Git projects use the resolved directory and filesystem identity.

`src/quattro_agent/collaboration.py` owns this resolution. The scheduler uses
the same repository ID for transactional global/agent/account/repository slots,
so startup reservation and runtime admission agree. Existing limits are not
increased by shared-tree operation.

## Writable ownership

Read-only discovery may overlap freely. Before an agent writes, it must declare
repository-relative file or directory scopes and acquire them through the
existing coordinator:

```text
quattro-agent collab claim --summary "authentication lifecycle" \
  --scope src/auth --scope tests/auth
```

The coordinator atomically rejects duplicate task summaries and overlapping
scopes (`src/auth` overlaps `src/auth/session.py`). The special `**` scope is
available only when a task must serialize the complete repository. If a task
has no declared scope, Quattro reports `scope not declared`; it must inspect
active claims and claim its intended write set before editing.

A parent session's child workers inherit its directory and coordination
identity. Read-only inventory/security/review workers have no writable scope.
`new-task`, `multi`, and `workflow run` accept repeatable `--scope` values so
independent work can claim `src/auth --scope tests/auth` rather than `**`.
A workflow uses `**` only when no safe scope was supplied. A writable
implementation worker uses its parent ownership or returns a proposed diff for
the owner. Conflicting edits are serialized or handed off;
Quattro never lets another session reset, clean, stash, discard, or overwrite
unknown modifications.

## Context and observability

Cooperative context reports the routing-independent facts needed by an agent:

```text
Working directory: /path/to/project
Isolation: shared_working_tree
Write ownership: src/orders/**
```

It also lists active same-repository sessions and their claimed scopes. Use
`quattro-agent collab status --json` for display-safe registry state.

## Recovery

The registry is private mode `0600`; its roots are mode `0700`. PID/start-time
checks and heartbeats release stale capacity without deleting source files.
Shared working-tree recovery preserves all modifications. Automatic destructive
Git cleanup, `git reset --hard`, branch switching, and discarding unknown
changes are prohibited.
