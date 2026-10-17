# Installation and operator CLI

## Requirements and isolated install

Python 3.11+ with SQLite FTS5. Runtime uses only the standard library. Git supplies repository provenance/ignore enforcement; plain non-Git document roots do not require it. No native agent or framework is required. Build/install uses ordinary setuptools/pip tooling, not a cloud AI service.

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
"$Q" --config "$C" register-source --project example --id code --root "$PWD" --kind repository --intent intended --exclude 'benchmarks/**'
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

Outputs are JSON except default `doctor`, which is compact human-readable output (`--json` selects machine output). `doctor` exits 0 healthy, 1 degraded, 2 unavailable. It never initializes/repairs/migrates storage or changes database permissions. Health/diagnostics remain compatible, but `doctor` is the operational readiness interface: endpoint health is not source coverage, configuration presence is not a client connection, and delivered context is not model use.

Integration diagnostics show the latest request/delivery and the latest scoped confirmed delivery within the most recent 100 host receipts separately. A new unconfirmed tool response does not erase an earlier observation; an older confirmation does not certify the new request. Missing end-to-end/citation observers remain explicitly unobserved.

Package upgrades affect new helper invocations and new MCP processes. Existing long-lived native MCP sessions retain their loaded code/config until reconnect; do not forcibly terminate unrelated active sessions to upgrade them.

### Inventory, freshness and recovery of indexing

```bash
"$Q" --config "$C" sources --project example --deep
"$Q" --config "$C" index code --dry-run
"$Q" --config "$C" index-selected --project example                 # plan only
"$Q" --config "$C" index-selected --project example --retry-failed  # plan only
"$Q" --config "$C" index-selected --source-id code --apply          # explicit approval
"$Q" --config "$C" inspect-source code
"$Q" --config "$C" inspect-source code --path docs/architecture.md
"$Q" --config "$C" doctor --project example --deep --details
```

Default batch selection includes intended/previously approved sources only; it never interprets all registrations as ingestion approval. Operations are sequential to avoid overloading the embedding service. A deep check hashes eligible content and reconciles scope with existing file fingerprints. Actual indexing removes moved/deleted/newly excluded evidence atomically; interrupted or failed replacement retains the committed snapshot, but retrieval still refuses non-current evidence. Fix missing roots or service failures before retrying. Transient database/transport retries are limited to three attempts with bounded exponential backoff. See [source-state semantics](configuration.md#source-states).

### Poor retrieval and result feedback

```bash
"$Q" --config "$C" query --project example ExactSymbol --strategy hybrid --explain
"$Q" --config "$C" feedback --project example RESULT_ID irrelevant
"$Q" --config "$C" feedback-export --project example
```

Explanations report actual BM25, cosine, RRF/boost/quality contributions, final rank and source revision/freshness. Unobserved context selection/delivery is null, not inferred. Feedback is attributed to the configured principal and source revision; it never verifies memory or silently changes ranking. Inspect cited eligible files and memory history rather than trusting scores alone.


## Memory operations

```bash
"$Q" --config "$C" memory save --project example --category procedural \
  --content 'Reindex after moving documentation.' --reference 'code:docs/installation.md' --tag indexing
"$Q" --config "$C" memory recall --project example indexing --limit 10 --offset 0
"$Q" --config "$C" memory recall --project example --historical
"$Q" --config "$C" memory history --project example MEMORY_ID
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

Backup reserves writers across retrieval, memory and receipts (when present), then uses independent online read snapshots so WAL data is included consistently. New directories are private; database files and manifest are mode0600. The manifest records schema versions, hashes and source mappings; vectors, metadata, memory events, feedback and receipts are preserved. Full-store exports require writer authority covering every stored project/source/root; foreign private/unmapped history additionally requires full operator verification authority. A narrowed reader/publisher cannot use backup as an inspection bypass. Legacy import remains copy-only; see [migration](MIGRATION.md).

```bash
B=/srv/private-backups/quattro-snapshot
R=/srv/private-recovery/quattro-restore-check
"$Q" --config "$C" restore "$B" "$R"    # refuses an existing destination
"$Q" --config "$C" doctor --backup-check "$B" --recovery-check "$R" --json
```

Restore validates authorization, schema, checksums, SQLite integrity/foreign keys and document/source links before declaring recovery verified. It never overwrites a live store. Inspect the manifest's source mappings, create an operator-reviewed separate configuration pointing at `R`, then exercise search and memory history before any deployment cutover. Restored vectors/FTS require no rebuild when compatible; explicitly reindex only changed sources. A partial restore lacks a verified recovery marker and must not be activated. Keep pre-cutover snapshots; rollback means selecting the previous reviewed package/config/store, not restoring over a running database.


## Optional native clients and receipts

After explicitly approving native setup, use `scripts/configure_native.py` with an existing base config and an explicit source-registration manifest; `--install-clients` additionally deploys the omp extension and Codex MCP/task hook. This is separate from the default isolated installer. See [native integration](INTEGRATION.md) for source authorization, publisher identities, learned embeddings, hook trust, Herdr attribution and the requirement to start/reload native sessions.

```bash
quattro-intelligence-native --host omp status --session SESSION_ID
quattro-intelligence-native --host codex status --session SESSION_ID
```

Inside native omp, `/quattro` shows that session's receipts. Automatic task context never performs an index mutation: use an explicitly approved `quattro_index_source`/MCP `index_source`, or the operator `index SOURCE_ID` command, for missing/stale registered sources. An indexed source and a registered source are not the same claim.

```bash
"$Q" --config "$C" receipts --host omp --session SESSION_ID
"$Q" --config "$C" receipts --host codex --session SESSION_ID
```

Attempted records precede retrieval; ready/failure records link `request_id` and retain the same resolved project/source scope. A stuck `attempted` row is not a successful query. OMP confirms only the receipt's presence in host context; Codex `submitted` confirms flushed hook stdout, not later acceptance/citation. Check [integration](INTEGRATION.md) for trust, reconnect and diagnostic-vs-ordinary activity.

## Repeating retrieval measurements

```bash
PYTHONPATH=src python -m quattro_core.benchmark \
  --config /absolute/frozen-evaluation-config.json \
  --dataset benchmarks/reliability.json \
  --baseline benchmarks/reliability-baseline.json \
  --output /absolute/private-evaluation-report.json
```

Use the same authorized, frozen source/index revisions and budgets as the baseline; comparison rejects mismatched corpus/dataset fingerprints. The committed baseline/final reports contain no excerpts. Scope preparation, stored local snapshot locations, measurement definitions and limits are documented in [retrieval](RETRIEVAL.md#repeatable-evaluation) and the [test report](TEST_REPORT.md).



## Platforms and service policy

Linux startup, indexing, package installation and MCP were locally exercised. Portable memory/MCP CI is configured for Windows; Windows indexing and macOS runtime remain unverified. The default installer installs no HTTP service, background scheduler or systemd unit. The separately authorized optional local embedding user unit is described in the native integration guide. Clients start stdio servers themselves; do not restart unrelated installed desktop or agent services as part of intelligence setup.
