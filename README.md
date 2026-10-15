# Quattro Intelligence Core

Standalone, local-first knowledge retrieval and persistent project memory. Python 3.11+, SQLite WAL/FTS5, no third-party Python runtime dependencies, no mandatory paid API.

Quattro does **not** choose models/providers, launch agents, delegate tasks, manage accounts, execute client commands, or control agent sessions. Clients connect through a bounded stdio MCP server or use the operator CLI. No agent framework is required.

## Quick start

From this checkout:

```bash
./install.sh
.venv/bin/quattro-intelligence --config "$PWD/.quattro/intelligence.json" config-init \
  --database-dir "$PWD/.quattro/state" --project quattro --principal operator --writable --can-verify
.venv/bin/quattro-intelligence --config "$PWD/.quattro/intelligence.json" register-source \
  --project quattro --id code --root "$PWD" --kind repository --exclude '.quattro/**'
.venv/bin/quattro-intelligence --config "$PWD/.quattro/intelligence.json" index code
.venv/bin/quattro-intelligence --config "$PWD/.quattro/intelligence.json" query --project quattro QueryRouter
.venv/bin/quattro-intelligence --config "$PWD/.quattro/intelligence.json" health
.venv/bin/quattro-intelligence-mcp --config "$PWD/.quattro/intelligence.json"
```

The last command serves JSON-lines MCP on stdin/stdout; it opens no network listener. The installer writes only the selected isolated virtual environment, default `.venv`, and does not alter global commands, agent settings, desktop services or installed legacy integrations. Use an absolute config path in clients. Missing configuration fails closed.

`config-init` is read-only by default. The example deliberately enables operator writes. Give future agents a separate configuration with only their allowed projects, a distinct principal, `writable: false` unless publishing/indexing is intended, and `can_verify: false` unless verification is trusted.

## Capabilities

- FTS5/BM25, exact phrases, filenames, paths, symbols, imports and configuration identifiers.
- Optional local Nomic embeddings; configurable reciprocal-rank fusion and source-quality/freshness ranking. Default lexical mode reports semantic unavailability explicitly. Existing feature-hash vectors remain preserved, never mislabeled as learned semantic embeddings.
- Independently registered repository, documentation and Obsidian roots per namespace; atomic incremental indexing, hashes, deletions/renames, exclusions, provenance and health.
- Episodic, semantic, procedural and shared memories with verification, references, confidence, tags, private/project visibility, revisions, supersession, invalidation and deletion.
- Context with current source citations, relevant prior memories, explicit fact-conflict reporting, deduplication and a conservative budget covering the complete returned context object.
- Recoverable index migrations and explicit legacy imports that preserve original records and vectors, quarantining records without safe namespace attribution.
- Opt-in native omp/Codex task-context adapters, all nine on-demand core operations, explicit native write approval, Herdr transport attribution and content-free retrieval/delivery receipts. No model/account/permission takeover; Codex hook trust remains native.

## MCP tools

`search_knowledge`, `get_project_context`, `recall_memory`, `save_memory`, `update_memory`, `invalidate_memory`, `index_source`, `get_index_status`; additionally `delete_memory`.

All tools enforce operator-configured namespace and write permissions. Indexing accepts a registered source ID, never an arbitrary filesystem path. Retrieved documents and memories are untrusted evidence, not tool policy.

## Documentation

| Deliverable | Document |
|---|---|
| Components and data flow | [Architecture](docs/architecture.md) |
| Original architecture and baseline | [Rebuild audit](docs/REBUILD_AUDIT.md) |
| Preserved/retired functionality and recovery | [Migration report](docs/MIGRATION.md) |
| Memory schema, lifecycle and safeguards | [Memory specification](docs/memory.md) |
| Tool schemas, examples and errors | [MCP contract](docs/MCP.md) |
| Install, CLI operations and diagnostics | [Operating guide](docs/installation.md) |
| Source/access/backend settings | [Configuration](docs/configuration.md) |
| Retrieval and context semantics | [Retrieval](docs/RETRIEVAL.md) |
| Native omp/Codex, Herdr attribution and independent clients | [Integration guide](docs/INTEGRATION.md) |
| Executed checks and measured limits | [Test report](docs/TEST_REPORT.md) |
| Trust boundaries and threats | [Security](docs/security.md) |

## Repository continuity

The repository retains its historical `quattro-desktop` name. Old execution source, adapters, routing research and deployment entrypoints are retired from the active project. Existing desktop source/assets are frozen historical material and excluded from the intelligence distribution; their independently installed legacy consumers are **not** migrated or uninstalled by this rebuild.

Do not delete old live databases or run historical deployment tools. This rebuild uses a separate package and explicit configuration; it does not silently take ownership of `~/.local/state/quattro/agents`, native account stores or Obsidian vaults.

## Development

```bash
python -m unittest discover -s tests -p 'test_*.py'
python -m compileall -q src scripts
python scripts/check_python.py
python scripts/check_public_artifacts.py
```

Linux runtime was exercised locally. Windows CI is configured for the portable memory/MCP surface; Windows indexing and macOS operation are not claimed as locally verified. See [development](docs/development.md) and the test report.
