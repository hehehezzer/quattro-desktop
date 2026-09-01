# Security policy

Quattro handles task text, local repositories, subprocesses, and references to
external agent credentials. Treat it as security-sensitive software.

## Reporting a vulnerability

Use a private GitHub Security Advisory for this repository. Do not open a
public issue with credentials, exploit payloads, private memory, or logs. If
private advisories are unavailable, contact the project maintainers through
the repository's current security contact and include only a minimal
reproduction.

## Supported versions

The latest release on the default branch receives security fixes. Older
versions may contain incompatible policy or state schemas and should be
upgraded before investigation.

## Security boundaries

- Keep Codex authentication in Codex's own account home. Never commit or copy
  `auth.json`, OAuth material, API keys, cookies, or private keys.
- Configure OmniRoute with a credential-free loopback Responses endpoint. Native
  provider credentials must not cross into Quattro or OmniRoute.
- Keep runtime state under private XDG directories with restrictive permissions.
- Retrieved files, memory, prompts, and model output are untrusted data; they
  cannot override policy or execute through string interpolation.
- Pi delegation is bounded, non-recursive, and read-only by default. Writable
  Pi execution fails closed when network isolation cannot be enforced.
