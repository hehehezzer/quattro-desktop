# Installation and operator CLI

## Requirements and isolated install

Python 3.11+ with SQLite FTS5. Runtime uses only the standard library. Git is optional provenance support; no Codex, Pi, OMP, Jev, OmniRoute, Paperclip or Herdr is required. Build/install uses ordinary setuptools/pip tooling, not a cloud AI service.

```bash
./install.sh
# Equivalent, with a chosen isolated environment:
python scripts/install_local.py --destination .venv
.venv/bin/quattro-intelligence --help
```

Existing destinations must be isolated virtual environments. Symlinked destination/bin/package paths, global/system-site-package destinations and linked console targets are rejected. The installer does not register native integrations, global commands, desktop services or future agents. From source, `PYTHONPATH=src python -m quattro_core.cli ...` works without installation.

## Setup and independent sources

```bash
Q="$PWD/.venv/bin/quattro-intelligence"
C="$PWD/.quattro/intelligence.json"
"$Q" --config "$C" config-init --database-dir "$PWD/.quattro/state" \
  --project example --principal operator --writable --can-verify
"$Q" --config "$C" register-source --project example --id code --root "$PWD" --kind repository
# Register an independently located documentation/Obsidian root with its own ID.
"$Q" --config "$C" register-source --project example --id notes --root /srv/notes/example --kind obsidian --exclude 'Private/**'
"$Q" --config "$C" index code
"$Q" --config "$C" index notes
```

Choose an existing notes directory; the service never creates or scans an unspecified vault. `config-init` refuses to overwrite an existing config. Omit writer/verification flags for reader clients. Use a separate allowed namespace per project; `--project` can be repeated at setup.

## Retrieval, maintenance and server

```bash
"$Q" --config "$C" query --project example 'ExactSymbol' --limit 5 --offset 0 --source-id code
"$Q" --config "$C" context --project example 'How is durable memory stored?' --budget 4000
"$Q" --config "$C" index-status --project example
"$Q" --config "$C" index code             # incremental
"$Q" --config "$C" reindex code           # forced
"$Q" --config "$C" index code --reindex   # equivalent
"$Q" --config "$C" health
"$Q" --config "$C" diagnostics
"$Q" --config "$C" memory stats --project example
"$Q" --config "$C" serve
```

Outputs are JSON. Health checks retrieval and memory integrity, configured source status and semantic availability. Diagnostics reports runtime/storage/config metadata, not documents, credentials or arbitrary process environments. A failed last indexing attempt makes health unhealthy while committed previous evidence remains usable.

## Memory operations

```bash
"$Q" --config "$C" memory save --project example --category procedural \
  --content 'Reindex after moving documentation.' --reference 'code:docs/installation.md' --tag indexing
"$Q" --config "$C" memory recall --project example indexing --limit 10 --offset 0
"$Q" --config "$C" memory recall --project example --historical
```

Use the returned stable ID with `memory update --project example ID --content TEXT --expected-revision N`, `memory invalidate --project example ID --reason TEXT`, or `memory delete --project example ID`. For structured updates, supply `--patch /absolute/update.json`; supported fields are documented in MCP/memory docs. Save supports `--visibility private`, `--fact-key`, `--supersedes`, `--verification`, `--confidence`, repeated references/tags and `--file`/`--stdin` instead of `--content`. Do not put sensitive content on a command line or in permanent memory.

An active fact's content change requires a new `memory save ... --fact-key SAME_KEY --supersedes OLD_ID`. Verification is not automatic. CLI record limits equal storage limits; local file/stdin intake is capped at 1 MiB before record validation.

## Backups and compatible legacy import

```bash
"$Q" --config "$C" backup /srv/private-backups/quattro-snapshot
# Import into a NEW configured database directory, never an existing live target:
"$Q" --config /absolute/new-intelligence.json migrate /absolute/legacy-retrieval.sqlite3 \
  --project example --source-id code
```

The backup destination must be new/private; online SQLite backups include WAL data from both stores. Import copies originals, preserves IDs/vectors and quarantines unassigned records. It does not import task telemetry as factual memory. See [migration](MIGRATION.md) before operating on real data.

## Optional native clients and receipts

After explicitly approving native setup, use `scripts/configure_native.py` with an existing base config and an explicit source-registration manifest; `--install-clients` additionally deploys the omp extension and Codex MCP/task hook. This is separate from the default isolated installer. See [native integration](INTEGRATION.md) for source authorization, publisher identities, learned embeddings, hook trust, Herdr attribution and the requirement to start/reload native sessions.

```bash
quattro-intelligence-native --host omp status --session SESSION_ID
quattro-intelligence-native --host codex status --session SESSION_ID
```

Inside native omp, `/quattro` shows that session's receipts. Automatic task context never performs an index mutation: use an explicitly approved `quattro_index_source`/MCP `index_source`, or the operator `index SOURCE_ID` command, for missing/stale registered sources. An indexed source and a registered source are not the same claim.


## Platforms and service policy

Linux startup, indexing, package installation and MCP were locally exercised. Portable memory/MCP CI is configured for Windows; Windows indexing and macOS runtime remain unverified. The default installer installs no HTTP service, background scheduler or systemd unit. The separately authorized optional local embedding user unit is described in the native integration guide. Clients start stdio servers themselves; do not restart unrelated installed desktop or agent services as part of intelligence setup.
