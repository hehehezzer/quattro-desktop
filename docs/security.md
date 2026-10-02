# Security model

The public engine uses several deliberate boundaries:

- subprocesses use argument arrays, bounded timeouts, process-group cleanup,
  and a minimal environment allowlist;
- untrusted GitHub review workers require Linux `bubblewrap` filesystem
  containment; they receive only a temporary checkout, sanitized runtime home,
  and report directory, and fail closed when `bwrap` is unavailable;
- task and display state is written atomically with private directory/file
  permissions;
- paths are resolved and symlink-sensitive files are rejected where they cross
  trust boundaries;
- policy profiles prevent child authority escalation and full access requires a
  run-scoped confirmation;
- Codex account homes are isolated and native auth is never parsed or copied;
- direct and delegated OmniRoute calls use only a credential-free loopback
  Responses contract;
- Pi delegation is bounded and writable Pi execution fails closed when the
  runtime cannot enforce network restrictions;
- GitHub PR publication is opt-in and evidence-gated.

## Trusted workspace assumption

The native Codex CLI's `read-only` and `workspace-write` modes constrain writes
but are not a general host-filesystem read sandbox. Ordinary user-authorized
tasks therefore run in the requested workspace and must not be pointed at an
untrusted checkout when the host contains sensitive files. Use the contained
GitHub review workflow, a separate VM/container, or an OS policy supplied by
the operator when read isolation is required for another workflow. Quattro does
not claim that its policy metadata alone can enforce host-wide read isolation.

The security scan in `scripts/check_public_artifacts.py` checks tracked paths,
symlinks, private machine paths, credential-shaped values, and runtime
artifacts. It is a release gate, not a substitute for threat modeling.

Tasks carrying an external `nativeGrant` belong to the approving execution
boundary. Generic queue reconciliation does not dispatch them, and the ordinary
harness refuses execution before claiming a run. Native prompt tasks do not
install terminal-close signal handlers. A scoped integration must validate its
grant and boundary before claiming; it cannot use the generic adapter as fallback.

Repository status probes used for coordination, checkpoints and retrieval
metadata disable Git filesystem-monitor hooks explicitly. Repository
configuration must not turn a metadata query into host code execution.

The controlled native lifecycle scopes host repository metadata to identity
queries only. Git status and diff may execute repository clean filters, so they
are not used for native planning, startup or checkpoints. Unknown dirty state
is preserved; coordinator records retain this identity-only policy after the
native context ends, and unknown work is conservatively recoverable.
