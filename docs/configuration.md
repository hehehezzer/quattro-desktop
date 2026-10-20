# Intelligence configuration

Pass `--config` before the CLI subcommand, or to `quattro-intelligence-mcp`. The default is `~/.config/quattro/intelligence.json`; absence is an error, not a permissive fallback. Legacy `ai.json`, provider environment variables and global agent settings are not consumed.

Configuration is strict version-1 JSON. Unknown fields fail. Paths are absolute, without traversal or symbolic-link components. Missing source directories are retained for diagnosis, not silently counted as indexed; indexing requires an accessible directory. Identifiers use `[A-Za-z0-9][A-Za-z0-9_.-]{0,79}`.

```json
{
  "version": 1,
  "database_dir": "/srv/quattro/private-state",
  "projects": ["example"],
  "principal": "knowledge-reader",
  "writable": false,
  "can_verify": false,
  "embedding": "lexical",
  "fusion": {"rrf_k": 60, "lexical_weight": 1.0, "semantic_weight": 1.0},
  "sources": [
    {"id": "code", "project": "example", "root": "/srv/projects/example", "kind": "repository", "intent": "intended", "authority": 0.9, "exclusions": ["vendor/**", "benchmarks/**"]},
    {"id": "notes", "project": "example", "root": "/srv/notes/example", "kind": "obsidian", "intent": "undecided", "authority": 0.5, "exclusions": ["Private/**"]}
  ]
}
```

These example paths must be replaced with authorized existing roots. Prefer `config-init` and `register-source` to produce a runnable local configuration; the README uses the checkout itself.

| Setting | Semantics |
|---|---|
| `projects` | Nonempty unique authorized namespaces; every request names one |
| `principal` | Operator-assigned author and private-memory identity; never supplied by a tool caller |
| `writable` | Enables indexing and memory mutations; source registration remains local CLI only |
| `can_verify` | Permits verified memory writes/updates; writes still require `writable` and references |
| `embedding` | `lexical` default, or `local-neural`; no external API or automatic model download |
| `fusion.rrf_k` | Integer 1–1000; default 60 |
| Fusion weights | Finite 0–10; at least one nonzero |
| Source `kind` | `repository`, `documentation` or `obsidian`; provenance and conflict-authority tie breaking |
| Source `authority` | Finite 0–1; default 0.8; source-quality multiplier, not a verification grant |
| Source `exclusions` | Up to 100 relative glob patterns, at most 200 characters each |
| Source `intent` | `intended`, `undecided` (default), or `excluded`; registration alone does not approve bulk indexing |
| Source `exclusion_reason` | Required nonblank bounded reason when excluded; exclusions do not count as indexing failures |

A project can have multiple independent roots; notes need not live inside the repository. Source IDs cannot change projects. An operator-authorized root change is labeled stale and inaccessible to retrieval until an explicit index reconciles that same-project source atomically. Removing/excluding a source immediately removes query access without deleting historical storage.

## Source coverage

Configured roots are walked for supported text, Markdown, structured files and code. Git repositories honor tracked/untracked ignore policy; ignored files are not indexed. Built-in exclusions reject symlinks, credential-shaped names/content, `.env*`, private keys, `.git`, `.venv`, dependency/build/cache directories, `.secrets`, `.quattro` and backups. Add exclusions for generated benchmark reports, uploads and project-specific private material. Do not register a home directory or entire shared vault for convenience. Git is required to enforce repository ignore policy, but plain non-Git document roots can operate without it.

### Source states

| State | Meaning |
|---|---|
| `pending` | Registered, no committed successful snapshot; scope may still need a decision |
| `indexed` | A full source snapshot committed under the current ingestion policy; freshness is separately `not_tested` until a deep check |
| `stale` | A previous successful snapshot exists but contents/root/policy changed or the root is unavailable |
| `failed` | The latest attempt/check did not commit successfully, including an explicitly uncommitted/in-progress-or-interrupted marker; reason/retryability and last success remain visible |
| `excluded` | Operator deliberately denies this source, with a reason; never selected for retrieval or batch indexing |

`sources --deep` compares eligible content hashes, not mtimes. `indexed_at`/`last_success` and `last_attempt` are distinct. Interrupted attempts remain recoverable and retry is idempotent. An explicit indexing attempt establishes prior approval for an otherwise undecided source even if that attempt fails; a dry-run does not. Default `index-selected` includes only intended or previously approved sources and is a dry-run; `--source-id` and `--apply` are explicit operator choices. Registrations without approval remain `requires_scope_decision`, not assumed eligible ingestion.


## Identity and operating-system authorization

Use separate operator-controlled configs for reader and publisher clients pointing at the same databases. Give each principal only the allowed namespaces. `private` memories are author-only; `project` memories are available to authorized principals in that namespace. Project mutations are allowed to authorized writers, not necessarily just the original author.

Configuration is a trusted local boundary, not an OS sandbox: a client with filesystem access to the database or permission to replace its config can bypass application-level controls. Keep configuration and storage owned by the operator; use separate OS accounts/process permissions where hostile local clients are possible. `writable: false` prevents domain writes, not initial database creation/schema maintenance when opening storage.

## Embeddings

The retained local neural client uses a fixed loopback llama.cpp endpoint `127.0.0.1:20218` and Nomic text-v1.5 model identity. It does not start servers or provision models. With a pre-existing compatible local server running, set `embedding: "local-neural"` and reindex to populate learned vectors. Semantic responses say whether compatible vectors and the endpoint are available; lexical results remain usable when the endpoint stops. The model process should bind loopback only, disable its UI and restrict CORS. It remains a separately operated optional dependency, not an agent orchestrator.
