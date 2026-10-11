# Development

Python 3.11+, standard-library runtime, `src/quattro_core` package. Active commands: `quattro-intelligence`, `quattro-intelligence-mcp`. Package discovery is explicit; historical desktop/platform files are not intelligence runtime dependencies.

```bash
python -m unittest discover -s tests -p 'test_*.py'
python -m compileall -q src scripts
python scripts/check_python.py
python scripts/check_public_artifacts.py
```

Tests use temporary authorized source roots and SQLite databases. Paid APIs, agent frameworks, Jev/OmniRoute and a running desktop are unnecessary. The Windows CI subset exercises portable memory/MCP behavior; Linux source indexing uses POSIX safe-open semantics. Optional semantic quality must be checked against a real local model, not mocked vectors alone.

Exercise the actual installed CLI and an independent stdio client after significant changes. Verify restart persistence, namespaces, private visibility, source change/delete/rename, rollback, sensitive exclusions and compatible legacy imports. Keep original live databases untouched during development; use SQLite backups and temporary destinations.

`check_public_artifacts.py` scans the Git index, including newly staged files, and reads working content. Intentional deletions must be staged before that release guard; never stage ignored state, private notes or real database fixtures. The retained desktop tests protect unchanged historical assets, not a claim that the new core controls the desktop.

Update architecture/contracts/migration notes and changelog when behavior changes. Use reviewable local commits; no push, release tag, system installation or production activation is implicit. Future PostgreSQL or network transports must preserve existing access/transactional invariants and justify new dependencies.
