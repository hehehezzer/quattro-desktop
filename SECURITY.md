# Security policy

Quattro Intelligence Core stores private project knowledge and persistent memories. Treat source authorization, namespace/privacy isolation, write permissions, credential filtering and SQLite migrations as security-sensitive.

Report vulnerabilities through a private GitHub Security Advisory for this repository. Do not publish credentials, private memory, database dumps or identifying filesystem paths. If advisories are unavailable, contact maintainers through the repository's current security contact with a minimal synthetic reproduction.

The active intelligence interface is `quattro_core`/stdio MCP. Historical orchestration releases have incompatible security/schema contracts and are not part of the new runtime. Application-level principal/config checks are not an OS sandbox for clients that can rewrite configuration or read the database directly.

See [security architecture](docs/security.md) for allowlists, untrusted retrieval, pattern-detection limitations, permissions, backups and safe deployment boundaries. Never move native credentials into Quattro or expose a local embedding/MCP service publicly by default.
