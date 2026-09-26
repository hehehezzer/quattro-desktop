# TypeSafe credential resolution and live validation

## Storage and authority

Quattro's existing provider boundary is not a single file holding every provider
secret. Native Codex credentials remain in account-isolated native stores; Pi
keeps its native auth separate; execution provider credentials (including any
DeepSeek configuration) remain behind OmniRoute. Quattro's gateway calls use a
credential-free loopback transport. Those stores are not read or modified by
this feature.

TypeSafe's existing local source is the user environment.d file:

```text
$XDG_CONFIG_HOME/environment.d/60-quattro-typesafe.conf
```

On Linux with no XDG override this is
`~/.config/environment.d/60-quattro-typesafe.conf`. It contains the literal
`TYPESAFE_API_KEY` assignment. Keep this single existing source: no copy to
`ai.json`, native auth stores, task state, shell startup files, or repository.
No credential migration was needed on the validated host; its existing file
already had owner-only `0600` permissions.

The new centralized provider access boundary is
`quattro_agent.provider_access.resolve_typesafe_credential`:

```text
explicit TYPESAFE_API_KEY environment override
  > existing private environment.d assignment
  > unavailable

resolver > lifecycle monitor > anonymous worker stdin > fixed-origin Jev client
```

An explicitly empty or malformed environment override means unavailable; it
does not silently fall through to the stored credential. Resolution is uncached
and does not mutate `os.environ`, making overrides session/process-local.
Neither native Codex/Pi children nor telemetry receive the key. The dedicated
Jev child has a minimal environment and receives only the required provider
credential through its already-existing anonymous pipe.

The stored file must be regular, bounded to 16 KiB, non-symlink, and on POSIX
owned by the current user with no group/other access. Symlinked environment.d
is rejected. Windows relies on the user's existing directory ACL. Only one
literal assignment is supported, optionally quoted; shell commands, variable
expansion, duplicate assignments, invalid bytes and unsafe permissions fail
closed to unavailable. No shell is invoked and no errors include file contents.

`quattro-agent status` prints `TypeSafe credential: configured` or `missing`;
JSON status uses `typesafeCredential`. There is no prefix/suffix/fingerprint.
Enabled native launch reports one concise local-fallback warning if resolution
fails. This increment does not yet add the Jev launch selector or enabled default.

## Live API correction

Authenticated discovery returned aliases `jev-latest` and `jev-preview`.
System One requested with `jev-latest` returned canonical `jev-1.13.0`.
The previous requirement that the response model appear verbatim in the alias
catalog incorrectly rejected this successful evaluation. The client now accepts
a strictly numeric `jev-MAJOR.MINOR.PATCH` canonical response after verifying
the requested alias in the authenticated catalog. It still rejects unknown
unadvertised non-version identities and never substitutes the requested model.

## Live benchmark, credential integration increment

Command:

```bash
python scripts/benchmark_jev_live.py --samples 20 --timeout-ms 1500
```

This is **live TypeSafe, routing only**, not execution-model or first-token
measurement. Twenty repetitions of five synthetic non-sensitive cases,
100 turns per mode, alternating OFF/ON and ON/OFF ordering. Existing narrow
eligibility guards admitted only the debugging case (20 evaluations); other
cases were greeting, definition, explanation and repository modification.
The 1500 ms timeout is an explicit benchmark setting, not a default change.

| Metric | OFF p50/p95 (ms) | COOPERATIVE p50/p95 (ms) |
|---|---:|---:|
| Routing, all 100 turns | 0.473 / 0.648 | 0.446 / 756.662 |
| Routing, 20 eligible debugging turns | 0.590 / 0.792 | 745.857 / 799.753 |
| Fusion, all turns | 0 / 0 | 0 / 0.011 |
| Live System One RTT, 20 evaluations | unavailable | 358.339 / 405.528 |
| Authenticated catalog RTT | unavailable | 306.548 / 316.555 |

ON evaluation attempts per turn: median 0, p95 1, maximum 1. OFF: all zero.
There were no retries or >1 cases. All 20 successful responses identified
`jev-1.13.0`; total observed usage was 14,380 input and 4,200 output tokens.
No provider price was returned; routing cost and total task cost are unknown.

The eligible debugging case selected the same `account-1/gpt-5.6-terra` route
in both modes. This establishes authentication, parsing and latency, **not a
routing-quality improvement**. Catalog plus evaluation exceed the existing
300 ms default budget on this host. A separate live 100 ms worker deadline
probe returned `timeout`, killed/reaped its child and joined its monitor.
No live provider-failure injection was performed; HTTP/schema/network failures
remain covered by hermetic tests.

Live results must not be conflated with `benchmark_jev.py`, which remains a
simulated-provider benchmark. No native UI task execution or installed runtime
release was performed in this increment. Broad bundle usefulness, a measured
trivial-turn A/B, launcher/session integration, final timeout policy, independent
review, merge and deployment remain PR #31 completion gates.

## Hermetic validation

Tests use generated fake credentials only. To guarantee a test runner cannot
use a developer's stored live key, run:

```bash
TYPESAFE_API_KEY='' python -m unittest discover -s tests -p 'test_*.py'
```

Credential tests cover environment precedence (including empty override),
persistent resolution, restrictive permissions, symlinks/FIFOs, bounds,
malformed/duplicate assignments, no shell expansion, no cache/global mutation,
metadata-only status and pipe-only delivery without telemetry/output leakage.
Existing client tests verify error categories never include auth values or
provider bodies. Alias-only canonical model responses have regression tests.
