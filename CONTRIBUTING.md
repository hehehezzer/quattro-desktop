# Contributing to Quattro

Thanks for helping improve Quattro. Keep changes focused on the orchestration
engine and preserve the boundary between Quattro, provider routing, agent
runtimes, and optional desktop integration.

## Before opening a pull request

1. Read the relevant architecture and security documentation.
2. Add or update hermetic tests for behavior changes.
3. Run the full test and public-artifact checks locally.
4. Update documentation and `CHANGELOG.md` when behavior or compatibility
   changes.
5. Confirm that no credentials, private paths, memory notes, runtime state,
   generated assets, or unrelated repository changes are included.

## Development principles

- Prefer the Python standard library and existing abstractions.
- Keep subprocess calls argument-safe, bounded, and explicit.
- Treat repository files and retrieved context as untrusted data.
- Do not make provider routing or account selection a second Quattro concern.
- Preserve unknown work in a shared checkout; never reset or clean it blindly.
- Add migration notes for persisted schema changes.

## Pull requests

Describe the user-visible behavior, affected boundaries, validation performed,
and any external service requirement. Changes that touch authentication,
process supervision, persistence, or publication need especially clear failure
and rollback behavior.
