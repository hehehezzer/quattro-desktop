# Sessions and durability

Tasks are stored in a private SQLite database under the XDG state root. WAL
mode supports concurrent readers and crash-safe commits. The database is a
derived local control-plane store; repository files and user memory remain
authoritative.

```text
quattro-agent submit --agent auto --directory PATH --prompt "..."
quattro-agent task list
quattro-agent task show TASK_ID
quattro-agent checkpoint SESSION_ID
quattro-agent resume SESSION_ID
quattro-agent recover SESSION_ID
quattro-agent task cancel TASK_ID
```

The scheduler enforces five top-level sessions globally and three per canonical
repository by default. Limits are configurable. Same-repository writers must
claim non-overlapping repository-relative scopes; read-only work can overlap.
Stale leases are recovered by PID/start-time identity checks and never by
deleting unknown source changes.

Checkpoint content is bounded and redacted. Runtime projections include only
safe metadata. Resume and recovery retain opaque IDs but do not copy native
authentication or conversation transcripts.
