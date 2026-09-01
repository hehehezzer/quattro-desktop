# Core/Desktop deployment migration

Quattro previously tracked Core and Linux Desktop files in one
`deployment/manifest.json`. The first deployment status, doctor, or deployment
operation after this change validates and partitions that manifest into:

- `deployment/core-manifest.json`
- `deployment/desktop-manifest.json`, only when Desktop records exist

Only after both replacements are durably written is the old manifest moved to
`deployment/legacy/combined-manifest-<UTC timestamp>.json`. Rollback references
and recorded hashes are preserved. The migration never opens or modifies the
task database, WAL files, checkpoints, account homes, configuration, memory,
retrieval data, or Codex/Pi authentication.

Core and Desktop deployment operations now accept `--profile`. Desktop drift
or missing assets cannot invalidate Core parity. Existing release snapshots
remain under the same release root and remain eligible for rollback.
