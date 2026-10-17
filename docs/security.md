# Intelligence security and data integrity

## Trusted inputs

An operator controls configuration, source roots, namespace allowlists, principal identity, writer/verification capabilities and database filesystem permissions. MCP callers control only bounded tool data. Authorization comes from configuration, never retrieved content, a supplied author field or tool annotations.

Stdio starts no public listener. There are no execution tools, subprocess arguments derived from retrieved instructions, provider credentials, shell interpolation or automatic AI calls. Optional Git probes use bounded fixed argument arrays; optional embeddings use a fixed loopback client. Existing agents/services/global settings are not mutated.

## Filesystem containment

Indexing requires an existing registered source ID. Source registration is local CLI only. Source traversal excludes symlinks and configured/default sensitive/generated directories. Descriptor-relative no-follow opens prevent swapped parent/file links from escaping the root. Oversized, binary, unsupported, unreadable and credential-shaped content is not admitted as knowledge; traversal/embedding failures roll back replacement rather than silently deleting prior rows.

Exclusions are defense-in-depth, not an invitation to authorize entire home directories or shared vaults. Git-ignore patterns are not automatically the source allowlist. Explicitly exclude project-specific sensitive/generated files. Model/user prose can contain sensitive information that credential patterns cannot recognize.

## Memory and transport

Namespace/private-author conditions apply to retrieval, context, mutation and statistics. Memory writes are transactional; record validation, deduplication, fact checks, revision checks, FTS and audit changes commit together. Verified outcomes require configured verification capability and references, including edits to already verified records. Important facts use immutable keys and explicit supersession.

Recursive credential scans cover raw and serialized nested content and bounded escaped forms. Duplicate JSON keys, non-finite values, excessive sizes/depth and unknown tool fields fail. Errors do not echo arbitrary arguments, private content or exception traces. There is no automatic conversation ingestion.

Every returned evidence item is untrusted. Instructions embedded in a note cannot grant a tool permission, change configuration or execute anything inside Quattro. A downstream agent must also keep evidence separate from its governing instructions; Quattro cannot guarantee that a future client will resist prompt injection.

## Storage and recovery

Use private operator-owned storage directories and mode-0600 database files created before WAL/journal initialization. Reject symlink/hardlink database targets. WAL/full synchronization and transactional locks support independent connections. Both database quick checks are exposed by health. Unrecognized/future schemas fail rather than wiping data.

Online backups include WAL; protect them with the same privacy boundary as originals. Import copies legacy knowledge without changing the source, preserving original IDs/vectors/metadata, and quarantines ambiguous or unsafe attribution from active search. Old telemetry is not promoted into verified memories. Logical memory deletion does not promise forensic erasure from free pages/WAL/backups.

## Limits and deployment

The config is not an authentication protocol or filesystem sandbox. A process that can edit its config or inspect the database is an OS-trusted client. Use separate operating-system identities/permissions for hostile local clients. A reader config prevents domain mutations, but opening storage can create databases or perform schema maintenance.

General natural-language contradiction detection is not implemented. Explicit fact declarations and claims are compared; operator verification still requires review. Neural ranking depends on the local model and indexed compatible vectors; lexical fallback reports unavailability clearly.

No desktop/systemd/global-agent deployment is installed by this package. Frozen historical desktop files may still reference installed old execution commands; this rebuild does not upgrade those independent installed consumers. Any decommissioning or production cutover needs separate authorization.
