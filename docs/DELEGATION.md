# Codex-primary Pi delegation

Quattro keeps Codex as the primary coding session. Managed Codex sessions receive a
small policy instruction that permits one bounded Pi specialist only when isolating
repository context is cheaper than doing the work directly.

## Command

```text
quattro-agent delegate decide --kind exploration --objective "..."
quattro-agent delegate run --kind exploration --directory /path/to/repo --objective "..."
```

Supported kinds are `exploration`, `implementation`, `tests`, `review`, and
`security`. The conservative policy rejects obvious small edits, one-line fixes, and
simple configuration changes. Codex should normally use one worker; the configured
hard limit is three concurrent Pi workers.

When invoked from a launcher-managed Codex session, the worker is attached to the
active `QUATTRO_TASK_ID`. Only Codex parents may delegate, and the worker inherits the
parent's exact managed worktree, repository identity, branch, runtime namespace, and
cooperation context. It does not create a sibling worktree or consume a top-level
global/repository session slot. Pi workers cannot delegate recursively. Standalone
calls are available for diagnostics and tests.

## Context and authority

The worker receives only:

- the bounded objective and role;
- Quattro's existing routed retrieval context (2,500-token assembly budget);
- compact mandatory operational constraints relevant to the worker, including
  the configured default project root for clone/create work;
- the repository path;
- read-only `read`, `grep`, `find`, and `ls` tools.

The parent conversation is never copied. The former broad 64 KiB project snapshot is
not injected for delegated workers. Pi has no enforceable write sandbox, so delegated
implementation work remains read-only: Pi returns an exact proposed edit or patch,
then Codex integrates and validates it. Direct Pi behavior is unchanged.

## OmniRoute

Delegated workers use a Quattro-private, credential-free Pi runtime under private
harness state. Its custom `openai-responses` provider targets the existing loopback
OmniRoute endpoint and selects model `auto`, leaving route/model selection to
OmniRoute. The required Pi key field contains only the documented non-secret local
placeholder; no Codex, Pi, or OmniRoute credential is copied. Global Pi settings and
direct Pi sessions are not changed.

## Result and failure contract

Pi's JSON event stream is secret-scanned, reduced to the final answer, and retained as
a bounded artifact with these headings:

```text
STATUS
FINDINGS
FILES_CHANGED
VALIDATION
RISKS
NEXT_ACTION
```

The existing event ledger records requested provider/model, worker duration, token
usage, and retry count. Worker failures return a compact failure result to Codex. The
harness performs no automatic retry; Codex may retry once only when it can provide
materially better context.
