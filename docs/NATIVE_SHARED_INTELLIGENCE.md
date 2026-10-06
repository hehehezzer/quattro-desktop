# Native shared intelligence

Direct native sessions share bounded repository retrieval, configured memory
and RTK tools through the existing Python helper and host adapters. Current
Jev advice uses only the [model-authored v2 interface](DYNAMIC_DECISIONS.md).
Shared intelligence cannot choose a native account/model or expand permissions.

## Native integration

Pi owns one helper child for the session and shuts it down with that session.
Its supported pre-agent boundary supplies a capability snapshot and ongoing
authoring guidance. The native model creates decision-specific questions,
alternatives and scalar parameters for meaningful milestones. Optional existing
result checkpoints remind the model when evidence changes; they do not submit
fixed provider questions. `operational_decision` remains available for later
model-authored milestones.

Direct Codex exposes shared tools and the same decision schema through MCP.
The supported integration is an explicit tool boundary; it does not claim
complete ordinary-turn or native-tool interception. Managed sessions preserve
their separate control plane and avoid duplicate direct-native advice.

`decision_capabilities` reports observed shared-tool availability, RTK support
and retrieval bounds. An adapter's inventory can narrow that information.
Unverified native builtins remain unverified. Discovery is separate from
authorization, and model-authored options cannot turn absent capabilities into
available tools. A managed gate with no attested execution inventory reports
no affirmative capability map.

## Retrieval and RTK

Retrieval runs on demand within existing repository/branch, configured-origin,
result-count and context-budget limits. Retrieved material is untrusted evidence,
never policy. Index refresh, search, selected sources, returned context and
native delivery are distinct events. Nonempty results do not prove semantic
sufficiency or model reliance.

RTK status means availability was checked; it does not mean a command executed.
Actual execution retains bounded argument arrays, existing command restrictions,
timeout and output limits. Native Pi preserves its conservative preflight and
loop gate. Only exact existing read-only inspection vectors such as Git status
and Git diff integrity checking receive that read-only classification; arbitrary
RTK or shell arguments do not acquire a permission grant.

The ordinary native Pi adapter offers a default-off, session-only
`--quattro-shell-confirm` flag. In a TUI session with the existing operational
guard enabled, an opaque native `bash` invocation can request a human decision
for its exact command, working directory and explicit timeout of 1–300 seconds.
An affirmative native dialog authorizes only that invocation. Changed inputs,
session or model changes, cancellation, timeout and reused call identities
invalidate confirmation. JSON, print and RPC sessions cannot use this bridge.

The command executes with the native user's filesystem and network rights;
the working directory is not a sandbox. This bridge does not authorize protected
Projects workers, expand RTK restrictions, override another guard denial or
count as accepted Jev advice. Advisory on/off preferences control model
consultation; deterministic preflight and loop checks retain their independent
host control. Explicit host operational-guard settings remain authoritative.

Source support alone does not establish installed availability or real human
acceptance. Activate only a reviewed extension in a fresh coordinated session;
do not restart an active session to introduce the flag.

## Controls and diagnostics

`quattro-agent native status` is passive. It reports effective settings,
registration and separate ordinary/diagnostic evidence without contacting Jev,
retrieving evidence or executing RTK. `native trace --session SESSION_ID` requires
an exact session identity and does not guess the latest concurrent session.

`native set --jev on|off` controls the existing native preference. Pi's
`/quattro-jev on|off|status` keeps its supported session preference. Native
settings no longer expose a decision-category menu; obsolete category settings
are reported as ignored and removed when settings are written.

An unsafe symbolic-link configuration is rejected without reading its target.
It cannot activate authored advice, retrieval or RTK, authorize a guarded tool,
or receive a settings write. A missing configuration retains the documented
defaults; unsafe configuration is not an explicit instruction to disable a guard.
Ordinary Pi file tools also cannot rewrite the actual native control file,
including path aliases and hard links, to disable their own guard. Reviewed host
settings changes use the separate control path. This check does not inspect the
contents or effects of a shell command approved by the human.

`native probe --decision-stdin` requires one bounded authored v2 envelope through
private stdin. Without authored input it reports `native_authoring_required`
and performs no provider, retrieval or RTK activity. An optional explicit query
stays local to bounded retrieval; the diagnostic supplies no default question
or search text.

## Privacy and evidence

Authored provider content must be abstract and minimally disclosed. No prompt,
response, source, path, command, tool output or credential belongs in an
envelope or persistent decision telemetry. Credential resolution uses the
existing native/private sources without new grants or copies.

Telemetry separates requested work, confirmed provider attempts, validated
responses, accepted advice, delivery and application. Cached advice is not a
new call. Pi records confirmed delivery at supported host boundaries; model
reliance and unobserved application remain unknown or unverified. Local evidence
retains bounded retention and restrictive file permissions.

Configuration, registration and hermetic fixtures do not establish live native
adoption. Deployment must preserve installed hardening, backups and coordinated
sessions. Protected worker code/policy pins require their existing reviewed
cutover and grant mechanism; broad task approval does not silently change them.
Earlier static-category native experiments are retired historical evidence.
