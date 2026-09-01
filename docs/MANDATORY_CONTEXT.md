# Mandatory Operational Context

Quattro separates trusted operating constraints from retrieved evidence.

## Precedence

1. mandatory global policy and validated configuration;
2. shared workflow rules;
3. repository/project instructions;
4. current task requirements;
5. hybrid RAG evidence, which is always untrusted.

The authoritative default project root is `workspace.projectRoot` in
`~/.config/quattro/ai.json` (source example: `examples/ai.json`). It defaults
to `~/Projects`. Explicit user destinations win unless a higher-priority safety
restriction prevents them.

`quattro_agent.mandatory_context` builds the compact trusted prompt section and
resolves clone/create destinations independently of RAG. Agents can run the
same deterministic preflight with:

```text
quattro-agent workspace resolve --operation clone --repository OWNER/REPO
quattro-agent workspace resolve --operation clone --repository OWNER/REPO --destination /explicit/path
```

The result records the resolved destination and whether it came from explicit
user intent or mandatory policy/config. Harness tasks emit a compact
`context.assembled` event containing mandatory sources/policies, retrieval
route/methods/selected sources/budget, destination provenance, and delegated
constraint propagation. `workspace.destination_resolved` records explicit
preflight use when a task id is available.

Failure investigations use these distinct classes:

- mandatory-context discovery failure
- RAG retrieval failure
- reranking/context-budget failure
- context propagation failure
- instruction-adherence failure
- path/config resolution failure
- tool/execution failure

Do not diagnose a missed mandatory policy as a RAG failure unless diagnostics
show that the missing information was correctly classified as retrieved rather
than mandatory context.
