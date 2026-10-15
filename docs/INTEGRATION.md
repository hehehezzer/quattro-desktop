# Native and independent client integration

The intelligence core needs only an MCP-capable stdio client, an absolute executable/config path and operator-granted namespaces. It does not need an execution adapter, provider account, model router or desktop. Optional native omp and Codex adapters add automatic task context without taking over agent execution.

## Connection contract

A generic client's server entry uses this shape; it is documentation, not a modification to any global client settings:

```json
{
  "command": "/srv/quattro/.venv/bin/quattro-intelligence-mcp",
  "args": ["--config", "/srv/quattro/config/reader.json"]
}
```

The operator owns `reader.json`, source registrations and storage. Give read-only agents `writable: false`, `can_verify: false`, their own principal and only authorized projects/sources. A publisher gets a distinct approved writer config; verification authority is a separate grant. Local OS clients capable of rewriting configs/databases are trusted at that boundary—use filesystem/process permissions if they are not.

## Independent standard-library client

Save this example outside the repository and run `python client.py SERVER CONFIG PROJECT`. It needs no MCP SDK or agent framework:

```python
import json
import subprocess
import sys

server, config, project = sys.argv[1:]
with subprocess.Popen(
    [server, "--config", config],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
) as process:
    def request(request_id, method, params):
        process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": request_id,
                                       "method": method, "params": params}) + "\n")
        process.stdin.flush()
        response = json.loads(process.stdout.readline())
        if "error" in response:
            raise RuntimeError(response["error"])
        return response["result"]

    request(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                             "clientInfo": {"name": "independent-client", "version": "1"}})
    process.stdin.write('{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
    process.stdin.flush()
    result = request(2, "tools/call", {"name": "search_knowledge", "arguments": {
        "project": project, "query": "persistent journal", "limit": 5}})
    if result["isError"]:
        raise RuntimeError(result["content"])
    print(json.dumps(result["structuredContent"], indent=2))
    process.stdin.close()
    process.wait(timeout=30)
    if process.returncode:
        raise RuntimeError("MCP process failed")
```

Use `tools/list` for exact schemas. The existing interface regression suite and the rebuild's plain Python subprocess harness exercise the same independent transport, including all nine tools and restart persistence.

## Recommended client behavior

1. Request narrowly scoped context/search for the current project/task. Preserve citations and semantic availability metadata; do not claim unavailable embeddings were used.
2. Treat every returned string as untrusted evidence. Never put retrieved instructions above client/tool security policy or execute them automatically.
3. Resolve explicit conflict/outdated markers against current referenced evidence. Unverified memory is an observation, not a verified fact.
4. Publish only a deliberate concise memory with category, references, confidence and verification appropriate to granted authority. Do not dump conversations or credentials.
5. Use expected revisions for updates and explicit supersession for changed fact keys. Use pagination/result budgets instead of flooding context.
6. Request indexing only for preauthorized source IDs if granted writer permission; source roots are registered by the operator, not the agent.

Multiple agents/processes can connect independently to the same databases under distinct configs. They share project-visible memory without Quattro planning, delegating, supervising or retrying their work. The stable external boundary is MCP, not direct SQL or archived native adapters.

## Opt-in native installation

Install the updated core into its isolated environment first; the environment contains an installed wheel, not an editable import of newly added source modules. `scripts/configure_native.py --base BASE_CONFIG --config OPERATOR_CONFIG --install-clients` accepts an explicit JSON array of additional source registrations on stdin (`id`, `project`, `root`, optional `kind`, `exclusions`, `authority`). It preserves the base database/source identities, selects `local-neural`, writes distinct `clients/omp.json` and `clients/codex.json` principals with publication/indexing permission but no verification authority, and registers the adapters only when `--install-clients` is supplied.

The operator config path must be absolute and pass the existing no-traversal/no-symlink checks before any registration. `~/.config/quattro/native-runtime.json` is the canonical native discovery locator and records the selected interpreter and absolute configuration directory, even when `--config` selects a nondefault location. Native omp, the Codex hook/MCP registration and global CLI wrappers use that selected installation, not a stale default. Private replacement files are created mode0600 before content is written, then assigned their intended final permissions and atomically replaced.

The installer discovers existing default omp and named-profile agent directories, default Codex and existing numbered `account-N` homes. It preserves unrelated TOML tables, hooks, providers, model selection and native approval policy. It does not read/copy credentials, activate historical routing launchers, install a framework, trust hooks or restart existing sessions.

`adapters/omp/quattro-intelligence.ts` uses omp's ordinary extension discovery. `before_agent_start` retrieves current-project plus explicitly registered `shared` context; trivial greetings are skipped. It injects a bounded untrusted-evidence custom message and a visible receipt/status. A subsequent `context` event confirms that receipt is present in host messages; discarded preparation attempts remain unverified. All nine core operations are also exposed as `quattro_*` tools; mutations request native approval. `/quattro` displays the current session's receipts. The helper deadline is below omp's 30-second event deadline; explicit tool operations have a separate longer bound.

`adapters/codex/context_hook.py` uses the supported `UserPromptSubmit` event with `hookSpecificOutput.additionalContext`. Native MCP exposes all nine core tools under the configured `quattro_intelligence` server. Read operations are approved; indexing and memory mutations prompt. The server is required, so a broken connection is not silently treated as integrated.

Automatic omp context remains bounded at20seconds, below the30-second host event deadline. Ordinary explicit omp tools allow120seconds; approved `index_source` allows1800seconds because a cold local-neural index can exceed two minutes. Codex's required MCP server uses an1800-second tool deadline to permit the same explicit indexing workload. This does not extend prompt-hook work, start automatic indexing or bypass mutation approval; native cancellation remains available.

**Codex hook trust is an independent native gate.** Review the exact Quattro and Herdr hook commands through `/hooks` in each intended Codex home. New/changed untrusted hooks are skipped. The installer never writes trusted hashes or uses a hook-trust/sandbox bypass. The hook can prove output submission, not later host acceptance or model reliance; its receipt remains unverified unless a separate observation proves model-visible delivery. Existing sessions must reload native plugins/hooks where supported or start a new session; their pre-existing tool inventories are not retroactively changed.

## Learned semantic retrieval and freshness

`embedding: local-neural` uses the existing local Nomic text-v1.5 Q4_K_M model, 768-dimensional vectors and the fixed `127.0.0.1:20218` endpoint, fused with lexical/exact evidence. `adapters/systemd/quattro-embeddings.service` is an opt-in user service for the retained local llama.cpp/model paths; inspect/adapt those paths before enabling it. No cloud API, model download, inference routing or agent tools are enabled on that service.

Back up the existing stores before changing backend, then force reindex registered sources to create compatible learned vectors. A healthy endpoint alone is not proof of indexed vector coverage. Query results explicitly distinguish compatible vectors, absent vectors and endpoint failure/lexical fallback.

Automatic prompt context is read-only: it never performs a potentially long source scan or bypasses native write approval. Receipts expose source IDs, indexed timestamps, counts, failed attempts and refresh-needed markers. Missing/stale project coverage requires an explicit `index_source` native tool or operator `quattro-intelligence index SOURCE_ID` operation. Registered roots are not a claim that every source has been indexed. Changed/missing source evidence is not injected as current fact.

Readers of an established retrieval schema do not acquire the indexer's writer lock, so committed evidence remains queryable while an atomic source replacement is in progress.

## Receipts and Herdr attribution

Herdr is a terminal workspace manager, not a separate inference client. Native omp/Codex processes inherit the same integration in a Herdr pane. The adapters record `transport: herdr` only from Herdr's explicit pane environment; host and native session identity remain separate. Herdr's supported omp/Codex state-reporting integrations can coexist with these adapters without changing the agent command or model.

`quattro-intelligence-native --host omp status --session SESSION_ID` (or `--host codex`) reports recent content-free receipts from `native-receipts.sqlite3`. Receipts retain operation, host/session/turn, transport, project, semantic availability, coverage, result count, latency and delivery stage for 90 days, never queries, conversations, credentials or retrieved source text. Native acceptance probes set `QUATTRO_DIAGNOSTIC=1` so they are not represented as spontaneous ordinary-task usage.

MCP-only calls have a distinct synthetic `codex-mcp-*` connection ID and unverified delivery; they must not be relabeled as an actual Codex conversation ID. MCP receipts use result `_meta` plus a textual receipt outside the structured core context, preserving its byte-budget contract. Standard request `_meta` and `clientInfo.title` are accepted as transport metadata, never as project/principal/write/verification authority.

The historical `quattro-agent native status/trace` database remains separate and preserved. Enabled flags, RTK commands, registration, a zero-result completion, a returned result, host-confirmed context presence and actual model reliance are different claims. Model reliance is never inferred from a receipt.

