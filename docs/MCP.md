# Standalone MCP contract

Launch `quattro-intelligence-mcp --config /absolute/intelligence.json`, or `quattro-intelligence --config /absolute/intelligence.json serve`. Transport: one UTF-8 JSON-RPC 2.0 object per newline on stdin/stdout. No HTTP listener, shell execution, agent dependency or network exposure is enabled. Protocol version: `2025-06-18`.

`initialize`, `ping`, `tools/list` and `tools/call` are supported. Send `notifications/initialized` after initialization. Notifications never execute mutations or return responses. Exact machine-readable input schemas are published by `tools/list`; additional unknown arguments are rejected.

Initialization accepts the standard optional `clientInfo.title`. Standard request-parameter `_meta` objects (including progress tokens) are accepted and discarded before operation validation; metadata never supplies project/principal/write/verification authority. Tool arguments remain strict.

## Tool inputs

All project/source/identity identifiers must also satisfy configuration validation. Optional fields use documented defaults. Pages: `limit` 1–50 (default 10), `offset` 0–100000 (default 0). Queries: up to 2,000 characters. `source_ids` accepts up to 64 registered IDs belonging to the requested project.

| Tool | Required fields | Optional fields / result |
|---|---|---|
| `search_knowledge` | `project`, `query` | page, `source_ids`, `strategy` (`keyword`/`semantic`/`hybrid`, default hybrid), `explain` boolean; results, semantic status, coverage/degradation warnings, optional actual score explanation |
| `get_project_context` | `project`, `query` | `budget` 512–32768 (default 2000), `limit`, `source_ids`, `strategy`; knowledge, memories, conflicts, outdated markers, warnings, semantic status and complete budget accounting |
| `recall_memory` | `project` | `query` (empty allowed), page, `historical`, `category`, `tags`, `verification`; authorized records and page metadata |
| `save_memory` | `project`, `content` | category, references, confidence, verification, tags, metadata, visibility, fact_key, supersedes; complete stored record |
| `update_memory` | `project`, `id`, `patch` | patch: content/category/references/confidence/verification/tags/metadata/fact_key/expected_revision; immutable visibility/author/project |
| `invalidate_memory` | `project`, `id`, `reason` | reason at most 2,000 characters; invalidated record |
| `delete_memory` | `project`, `id` | deletion result; removes content-bearing history, not backups |
| `index_source` | `source_id` | `reindex`, `dry_run` booleans; structured incremental plan/result, fingerprint, counts and committed policy revision; never a caller-supplied root |
| `get_index_status` | `project` | `deep` boolean; five source states, scope classification, last success/attempt/failure/retryability, file/document counts, fingerprint and separately assessed freshness |

Save defaults: `semantic`, confidence 0.5, `unverified`, `project` visibility, empty references/tags/metadata. Categories and verification are enumerated in the [memory specification](memory.md). Save content: at most 16,384 characters and 24,000 UTF-8 bytes; entire record at most 32,000 UTF-8 bytes. Metadata: at most 32 top-level properties. References/tags: at most 50 unique entries, each at most 1,000 characters. Updates require a nonempty patch; `expected_revision` rejects stale writes. Supersession is a new save referencing an existing ID, not a content update to an active fact.

## Wire examples

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"independent-client","version":"1"}}}
{"jsonrpc":"2.0","method":"notifications/initialized"}
{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"search_knowledge","arguments":{"project":"example","query":"persist_lesson","limit":5,"source_ids":["code"]}}}
{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"save_memory","arguments":{"project":"example","category":"procedural","content":"Reindex the configured source after renaming documentation.","verification":"unverified","references":["code:docs/installation.md"],"tags":["indexing"]}}}
```

Successful calls return `result.isError: false`, `result.structuredContent` and an equivalent JSON text content item. Knowledge citations carry source ID/kind, namespace, path, line range, document/file hashes, freshness and optional commit SHA. Content is always marked `untrusted: true`; no returned string changes Quattro's authorization.

When the operator sets `QUATTRO_NATIVE_HOST=omp` or `codex`, calls persist scoped attempt/result/failure receipts and return terminal receipt metadata in `result._meta["quattro.receipt"]`. Successful responses also include a separate textual receipt. Project/source scope is server-resolved, including index-source targets; failure/attempt records retain the same restrictions. `request_id` correlates terminal records with durable attempts. Core structured context retains its budget; surrounding receipt metadata is outside it. Synthetic MCP connection IDs do not prove native conversation identity, host delivery, acceptance, citation or model reliance.

## Errors and limits

Tool failures return `isError: true` with bounded generic messages: operation not permitted, memory inaccessible, invalid data, or operation unavailable. They do not echo supplied credentials, private content, arbitrary filenames or exception traces. JSON-RPC errors: parse/oversize `-32700`, invalid request `-32600`, unknown method `-32601`, invalid RPC parameters `-32602`, response unavailable/oversize `-32603`.

Frames are limited to 65,536 bytes; an oversized frame closes the stream rather than executing its tail. Response limit: 1 MiB. JSON duplicate keys, non-finite numbers, excessive nesting/property/list sizes and invalid types fail. Context's budget is a conservative UTF-8-byte upper bound on the complete context object, not the surrounding JSON-RPC wrapper and not an exact tokenizer count.

## Authorization

Configured principal, allowed projects, source IDs, `writable` and `can_verify` are authoritative. A caller cannot supply author/permissions/root/path/execution arguments. All mutations require explicit writer configuration; verified resulting records also require verification permission and references. Private memory is author-only. Source registration and database import/backup are operator CLI operations, intentionally absent from MCP.

A local stdio client with direct write access to operator configs/databases is trusted at the OS boundary; use separate permissions for hostile clients. See [security](security.md) and [integration](INTEGRATION.md).
