# Troubleshooting

## `configuration is missing` or invalid

Run `quattro-agent config init`, verify the path in `QUATTRO_CONFIG`, and then
run `quattro-agent config validate`. A config containing a real secret should
be discarded and recreated; Quattro never needs a provider API key in JSON.

## Codex contract failure

Run `quattro-agent doctor --json`. Confirm that the selected Codex home has a
non-secret `config.toml` using provider `omniroute`, `wire_api = "responses"`,
`requires_openai_auth = false`, a loopback `base_url`, and the approved shared
catalog. Authenticate Codex only through its own CLI.

## OmniRoute unavailable

Confirm the gateway is running at `QUATTRO_OMNIROUTE_BASE_URL` and that its
Responses endpoint and four Quattro route labels are enabled. Quattro reports
the failure and does not fabricate a delegated result.

## Pi unavailable or rejected

Pi is optional. Disable delegation or use Codex directly. Writable Pi work is
expected to fail closed unless the installed Pi runtime can enforce the
requested network policy.

## Stale task/session

Use `quattro-agent sessions status`, `quattro-agent sessions clean`, or
`quattro-agent task reconcile`. Quattro verifies process identity before
retaining a running record and preserves source changes during recovery.

## Desktop integration

The Hyprland/Quickshell files under `src/` are optional. Install Quickshell,
ensure the helper commands are on `PATH`, and run the checks in
`docs/desktop.md`. A missing desktop dependency must not block core Python
tests.
