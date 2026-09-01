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
