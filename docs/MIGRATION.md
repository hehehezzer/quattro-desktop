# Migration and data preservation

This guide preserves the Intelligence cutover and legacy-data recovery contract. Historical observations below describe the 2026-10-11 rebuild, not the current installer or installed desktop state. The active product is standalone retrieval and persistent memory; optional desktop setup is documented in the [README](../README.md#optional-arch-desktop).

## Historical baseline and rollback

Original branch: `feat/dynamic-main-integration`; original revision: `dc88f61d84c0765078a2292823abfca29a39e533`. The working tree was clean before the rebuild, developed on `feat/intelligence-core-rebuild`.

Before destructive source retirement, a complete Git bundle was created and verified. Six actual SQLite stores were backed up using SQLite's online backup API, and every backup returned `PRAGMA quick_check = ok`. Durable copies are held in a private local preservation directory outside the repository: `pre-rebuild.bundle` and `databases/`. Their exact workstation location is supplied in the delivery message, not committed into public documentation.

No original live database, installed desktop service, native agent integration, provider setting, account store, deployment or unrelated repository was changed. Git history retains removed code; the bundle provides a second recovery path. Restore into a separate checkout/directory before considering any explicitly authorized deployment.

## Preserved and changed

| Area | Result |
|---|---|
| Working `retrieval.py` / `benchmark.py` | Moved into `quattro_core`; FTS, vectors, code units, graph edges, ranking and regression coverage reused |
| Index v2 → v3 | Non-destructive upgrade with private online backup; per-document embedding identity retained; no generation-mismatch wipe |
| Repository knowledge | Explicit source/namespace ownership layered over original schema; full-tail chunks/import/config units; atomic source replacement |
| Structured memory | New independent WAL/FTS5 schema; explicit verification, references, identity/privacy, revision and fact lifecycle |
| Shared intelligence interface | Replaced execution-coupled imports with standalone knowledge/memory/MCP boundary |
| Package/install at cutover | `quattro-intelligence-core` 1.0.0; isolated core installation, no implicit native/global registration |
| Desktop/platform assets | Retained separately and excluded from the Intelligence distribution; no reconnecting installed execution consumers to incompatible contracts |

Source retirement removed obsolete execution modules, adapters, execution-only tests/benchmarks, routing research and deployment entrypoints. Model/provider/account routing, agent spawning, task/session supervision and execution dashboards are not Intelligence responsibilities. The package exports no execution CLI or wildcard execution API.

Retained desktop source may still reference independently installed historical commands. Those installed consumers were not new-core clients and were deliberately not uninstalled, restarted or migrated by the rebuild. Desktop setup now remains a separate opt-in profile; it does not restore the retired execution system.

## Real database migration proof

Migration ran against the private backups, never live originals. The configured mapping used this project's actual repository root. Document IDs and every embedding byte were compared in ordered SHA-256 aggregates; counts and SQLite integrity matched, and source-file SHA-256 remained unchanged.

| Legacy database | Documents preserved | Safely assigned to project/source | Preserved in quarantine |
|---|---:|---:|---:|
| Feature-hash retrieval | 46,440 | 17,341 | 29,099 |
| Local-neural retrieval | 2,063 | 1,977 | 86 |

Assignment requires matching original repository identity/project or an authoritative path contained within the explicitly configured source root. It does **not** rename all records into a caller-selected project. Other-project/global/ambiguous records remain present in the copied database and inaccessible through active source search. Historical branches/content remain preserved; live provenance checks mark missing/changed source evidence rather than presenting it as current.

A fixture migration also preserved an explicitly attributed legacy memory and its vector, importing it as **unverified** structured memory with original IDs/hashes/time metadata and references. Verified status is never invented.

Durable migrated copies were also created in this checkout's ignored `.quattro/migrated/feature-hash/` and `.quattro/migrated/local-neural/`. Read-only configurations `.quattro/archive-feature-hash.json` and `.quattro/archive-local-neural.json` expose only safely attributed Quattro evidence through the new CLI/MCP. Both archive MCP queries and denied archive indexing were exercised. All original records, including quarantined rows/vectors, remain on disk; these private local artifacts are not packaged or committed.

The normal `.quattro/intelligence.json` uses separate current-source databases, so historical branch/retired-code evidence cannot silently override fresh project context. A real online CLI backup of both current databases was created in `.quattro/backup-acceptance/`. Do not reindex the preserved archives unless deliberately replacing historical derived data.

## Not safely promoted to factual memory

- Existing execution store: schema version 4, 925 task rows, 25,335 events and 2,208 checkpoints. Historical execution records are backed up, not interpreted as facts.
- Native intelligence / pre-live stores contain event telemetry, not verified project memory.
- A separate nested intelligence database is routing-research schema version 4 with 1,109 routing records. It is backed up as `intelligence-routing.sqlite3`, not connected to the new core.
- Unscoped/global records cannot be assigned without operator evidence. Credential-shaped content, oversized/incompatible memory records and historical/inactive records remain preserved in the copied legacy store, not silently dropped or exposed as new knowledge.

Neither real retrieval store contained compatible explicit/approved memory rows to promote automatically. Their original vectors/metadata remain intact; the new memory database does not pretend to contain historical conversational knowledge.

## Operator migration procedure

1. Stop writes only if required by the operator's own deployment procedure; SQLite online backup itself includes committed WAL data. Keep private backups and original paths.
2. Create a **new** intelligence configuration/database directory. Register only the known project/source root. Never point migration at an existing target database.
3. Run `quattro-intelligence --config NEW_CONFIG migrate OLD_RETRIEVAL --project PROJECT --source-id SOURCE`.
4. Inspect reported preserved/assigned/quarantined/imported counts, run health, and query representative references. Reindex explicitly when current sources should replace historical derived records; unchanged legacy vectors are not regenerated merely on schema open.
5. Keep originals and quarantined records until a deliberate reviewed retention decision. No task telemetry or ambiguous namespace is automatically imported.

Migration and schema changes are local SQLite implementations; PostgreSQL/pgvector and other legacy database formats are not implemented. Recoverable copies are the boundary, not destructive in-place conversion.
