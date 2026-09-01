# Memory and retrieval

Memory is an optional integration. The starter configuration sets
`memory.enabled` and `enforceOnLaunch` to `false`, so a new user can run and
test Quattro without an Obsidian vault.

When enabled, configure two user-owned Markdown roots: a shared/long-term vault
and a project vault. `quattro-agent memory init` creates a generic safe
structure without importing existing notes. Existing files are preserved.

Quattro may build a private SQLite/FTS5 derived index for repository files,
approved Markdown notes, checkpoints, and explicit memory entries. Queries are
scoped by repository and branch; secret-shaped files and values are rejected.
The index can be rebuilt and must not be committed.

Never store passwords, API keys, OAuth tokens, cookies, private keys,
authentication files, raw prompts, raw model responses, arbitrary process
environments, or sensitive personal information in memory. Treat all retrieved
content as untrusted evidence, not instructions.
