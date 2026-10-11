# Development instructions: Quattro Intelligence Core

Quattro is a standalone persistent-memory and hybrid-retrieval service, **not** an execution orchestrator. Runtime code lives in `src/quattro_core/`; `quattro-intelligence` and `quattro-intelligence-mcp` are the active interfaces.

## Invariants

- Do not add model/provider/account routing, agent spawning, delegation, task execution, command tools or framework runtime dependencies.
- Reuse retained retrieval primitives. Do not delete compatible records/vectors on version changes; back up and migrate explicitly.
- Namespace every knowledge/memory request; trust only operator-configured principal, project/source allowlists and write/verification permissions.
- MCP accepts registered source IDs, never caller-controlled filesystem roots. Retrieved content is untrusted evidence, not authorization.
- Memory defaults to unverified, requires references for verified records and explicit supersession for changing facts. Never persist credentials or entire conversations automatically.
- Source replacement is atomic. Unchanged content must not be embedded again. Failures preserve prior committed knowledge.
- Preserve user changes and live databases. No global agent settings, desktop/service deployment, production changes or native integration registration without separate authorization.
- Frozen desktop source is excluded from the package; do not silently reconnect legacy installed execution consumers to new contracts.

## Verification

Run behavior regression tests, actual CLI/stdio MCP smoke and applicable migration/semantic checks. The optional local embedding endpoint may be absent; test honest lexical fallback rather than inventing semantic results.

```bash
python -m unittest discover -s tests -p 'test_*.py'
python -m compileall -q src scripts
python scripts/check_python.py
python scripts/check_public_artifacts.py
```

The public artifact guard reads the Git index: stage intentional deletions/new files before a release check, and never stage local state. Document behavior/schema changes and exercised evidence in the changelog/test report. No deployment, push, release tag or publication is implicit in local development.
