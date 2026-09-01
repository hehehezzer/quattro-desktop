# Development

The project is Python 3.11+ with no runtime dependency outside the standard
library. The public package uses `src/` layout and exposes the
`quattro-agent` console script.

## Local checks

```bash
python -m unittest discover -s tests -p 'test_*.py'
python -m compileall -q src
python scripts/check_python.py
python scripts/check_public_artifacts.py
git diff --check
```

Use focused unittest modules while iterating, then run the full suite before a
release. Tests use temporary directories and fake subprocesses; paid Codex,
Pi, GitHub, OmniRoute, Hyprland, and desktop services are not required.

## Adding a feature

Keep request classification, tier routing, provider routing, execution, and
projection as separate concerns. Add a regression test for lifecycle and
failure behavior, document persisted-schema changes, and do not place prompts,
responses, credentials, or arbitrary environments into display-safe state.

## Release checks

Review `CHANGELOG.md`, run the CI-equivalent checks, inspect the staged file
list, run the public-artifact policy, and validate a fresh clone. Deploy only
with `quattro-agent deployment deploy` from the exact clean commit; it records
rollback inventory and removes retired mapped paths. Do not create or move a
release tag until the release owner approves the exact commit.
