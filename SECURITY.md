# Security policy

Quattro Intelligence Core stores private project knowledge and persistent memories. Treat source authorization, namespace/privacy isolation, write permissions, credential filtering and SQLite migrations as security-sensitive.

Report vulnerabilities through a private GitHub Security Advisory for this repository. Do not publish credentials, private memory, database dumps or identifying filesystem paths. If advisories are unavailable, contact maintainers through the repository's current security contact with a minimal synthetic reproduction.

The active intelligence interface is `quattro_core`/stdio MCP. Historical orchestration releases have incompatible security/schema contracts and are not part of the new runtime. Application-level principal/config checks are not an OS sandbox for clients that can rewrite configuration or read the database directly.

See [security architecture](docs/security.md) for allowlists, untrusted retrieval, pattern-detection limitations, permissions, backups and safe deployment boundaries. Never move native credentials into Quattro or expose a local embedding/MCP service publicly by default.

Release scans must complete successfully before publication is considered clean. `scripts/check_public_history.py` checks every commit reachable from `HEAD`; a failed Git marker or credential query is a scan failure, not evidence that no match exists. Investigate repository/object access and Git errors before rerunning. Do not reduce reachable-history coverage or add unreviewed exceptions merely to clear CI.

On 2026-10-21 the owner explicitly acknowledged one already-public, non-credential machine-path finding: commit `a58015ac9f2a477b0864e91287bb6d89efc60f90`, `src/restart-quickshell` line 19, blob `f6271236f5a94675534db101f38ea0255c08edda`. The scanner pins all these identities and the single home-path marker. The current script uses portable paths. This acknowledgment does not exempt credential checks, another marker, another blob, another location, or a later commit reintroducing that path. Published history is preserved, not rewritten.
