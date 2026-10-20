# Development instructions: Quattro Intelligence Core

Quattro is a standalone persistent-memory and hybrid-retrieval service, **not** an execution orchestrator. Runtime code lives in `src/quattro_core/`; `quattro-intelligence`, `quattro-intelligence-mcp` and the optional `quattro-intelligence-native` boundary are the active interfaces. Native adapters must preserve host model/account/permission/delegation controls and may not bypass hook trust.

## Invariants

- Do not add model/provider/account routing, agent spawning, delegation, task execution, command tools or framework runtime dependencies.
- Reuse retained retrieval primitives. Do not delete compatible records/vectors on version changes; back up and migrate explicitly.
- Namespace every knowledge/memory request; trust only operator-configured principal, project/source allowlists and write/verification permissions.
- MCP accepts registered source IDs, never caller-controlled filesystem roots. Retrieved content is untrusted evidence, not authorization.
- Memory defaults to unverified, requires references for verified records and explicit supersession for changing facts. Never persist credentials or entire conversations automatically.
- Source replacement is atomic. Unchanged content must not be embedded again. Failures preserve prior committed knowledge.
- Preserve user changes and live databases. No global agent settings, desktop/service deployment, production changes or native integration registration without separate authorization.
- The optional Arch desktop profile is separate from the intelligence package. Keep feature selection, portable hardware defaults, reversible configuration backups and explicit native registration; do not reconnect retired execution consumers to new contracts. Never activate the running desktop as a side effect of setup.

## Verification

Run behavior regression tests, actual CLI/stdio MCP smoke and applicable migration/semantic checks. The optional local embedding endpoint may be absent; test honest lexical fallback rather than inventing semantic results.

```bash
python -m unittest discover -s tests -p 'test_*.py'
python -m compileall -q src scripts
python scripts/check_python.py
python scripts/check_public_artifacts.py
```

The owner's standing delivery requirement is mandatory: dedicated non-`main` branch → validate → commit → push the branch → open a PR to `main`. Verify the remote SHA and leave the task worktree clean; a local commit alone is not completion. This standing authorization covers branch publication, not merging, release tags, deployment or changes to native permissions. Report an actual blocker instead of silently omitting push or PR.
