# Quattro Development

## Repository layout

- `src/quattro-agent` — command-line control-plane entry point.
- `src/quattro_harness.py` — durable task lifecycle, context assembly, and
  execution supervision.
- `src/quattro_agent/` — policy, adapters, routing, persistence, retrieval,
  collaboration, recovery, and validation primitives.
- `src/quickshell/` — the single Quickshell UI.
- `src/hypr/` — Hyprland Lua configuration.
- `tests/` — Python unit and integration tests.
- `docs/` — operational and architecture documentation.

## Development workflow

1. Read project instructions and institutional memory.
2. Inspect current source and runtime state; preserve unrelated dirty changes.
3. Make the smallest compatible change and add focused regression coverage.
4. Run focused tests, then the full suite for release candidates.
5. Validate syntax and whitespace.
6. Update durable project memory only after validation.

```text
PYTHONPATH=src python -m unittest discover -s tests -p 'test_*.py'
python -m py_compile src/quattro-agent src/quattro_harness.py
python -m py_compile src/quattro_agent/*.py
git diff --check
```

## Release procedure

1. Ensure the intended source changes are reviewed and committed.
2. Confirm `git status` is clean and no secret or generated artifact is staged.
3. Run the full test suite and release checks.
4. Use `quattro-agent deployment deploy` from the exact clean commit. It
   creates a private rollback release, installs the validated source mapping,
   and removes paths retired by the new release; do not copy a dirty working
   tree into the runtime.
5. Verify manifest source/deployed parity and both Codex account contracts.
6. Smoke-test DIRECT and a non-mutating delegated Codex task in a disposable
   repository.
7. Only then create and push a reviewed annotated release tag such as `v1.0.0`.

## Commit organization

When the working tree is fully reviewed, prefer coherent commits rather than
mechanical splitting: runtime/architecture, tests, documentation, then release
metadata. Do not commit unrelated desktop assets, credentials, generated
artifacts, or temporary diagnostics merely to obtain a clean tree.
