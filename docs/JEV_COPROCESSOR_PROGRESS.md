# Default-enabled decision coprocessor — implementation in progress

Base: merged/deployed PR #30, `3393d0b`. This branch is not production-ready.
Production remains on the verified OFF-default baseline.

## Implemented foundation

`jev_preferences` provides immutable, strict boolean preference resolution and
versioned session metadata. Precedence is explicit CLI, explicit selector choice,
resumed session value, saved global default, then enabled. Absent legacy session
metadata is distinct from False. Invalid metadata fails validation rather than
silently enabling a disabled session. The record cannot contain a stale plan.
The resolver has no I/O, credentials, dispatch or routing authority.

This foundation is not yet connected to CLI/configuration/native persistence.
Therefore it does not change the current production or source launcher default.

## Bounded failure suppression

The existing lifecycle now suppresses provider workers for 30 seconds after
three consecutive provider/worker failures per evidence-store path in the same
process. Success resets the count; cancellation, absent credentials and local
telemetry failure do not count. Suppression is observable in turn evidence,
uses no retry thread, and retains the existing worker cancellation ownership.
Six hermetic regressions cover threshold/expiry, reset, isolation, bounded LRU,
no-worker suppression, and lifecycle-owned failure/retry/reaping.

This does not complete launcher integration or enable the default. The initial
credential blocker is superseded by the following credential integration.

## Validation of cooldown increment

- `python -m unittest discover -s tests -p 'test_*.py'`: 713 tests,
  OK (5 skipped).
- `python -m compileall -q src scripts`: passed.
- `python scripts/check_python.py`: PASS.
- `python scripts/check_public_artifacts.py`: PASS.
- `git diff --check`: passed.
- `python scripts/benchmark_jev.py --native --repetitions 6`: 72 turns per
  mode, balanced six-order rotation, simulated provider with real supervised
  children. OFF routing p50/p95 0.620/0.909 ms; COOPERATIVE 0.615/55.542 ms.
  Cooperative fusion p50/p95 0.008/0.011 ms; simulated evaluation RTT
  20.091/20.097 ms. Existing eligibility guards admitted only six observations
  per enabled mode. These are not broad coprocessor or live service results;
  no first-token, actual execution duration, actual usage or cost was measured.
- Scoped diff self-reviewed; independent review remains outstanding.

## Persistent credential integration and live evidence

The existing owner-only environment.d TypeSafe assignment is now resolved by
`provider_access`, with explicit environment override precedence, no secret
copies, no environment mutation and pipe-only delivery to the isolated worker.
Status exposes configured/missing only. Enabled native launch warns once if the
credential is unavailable. The deployment inventory includes the resolver.

Live validation found and repaired an alias/canonical model mismatch:
`jev-latest` is catalog-advertised, while System One returns `jev-1.13.0`.
Twenty live evaluations succeeded; RTT p50/p95 was 358.339/405.528 ms. Including
catalog and worker overhead, eligible native routing was 745.857/799.753 ms.
The old 300 ms default is too short for those observed round trips. No timeout
or enabled-default promotion was made. See [JEV_CREDENTIALS.md](JEV_CREDENTIALS.md)
for exact benchmark scope, usage, security boundary and remaining limitations.

Validation of this increment: 724 full-suite tests, 5 skipped; compileall,
Python hygiene, public artifact policy and diff checks pass. Tests explicitly
set an empty environment override to prevent accidental use of local credentials.

## Required remaining integration

1. Connect one compact native-style agent/Jev selector, CLI overrides, global
   default migration and session-specific persistence in Codex and Pi resume
   boundaries. Do not persist preferences via global mutable configuration.
2. Expand the existing typed Jev schema into one per-turn decision bundle;
   preserve the privacy boundary and validate the actual TypeSafe contract.
3. Use one canonical context to fuse learned, deterministic, historical and
   runtime evidence. Keep exact targets, constraints and dispatch Quattro-owned.
4. Run Jev and learned inference concurrently from the same frozen features;
   reuse the bundle downstream. No duplicate call on ordinary steps; material
   rerouting requires explicit evidence and a distinct transition identifier.
5. Connect the implemented process-local failure cooldown to complete session
   diagnostics; add warning-once behavior, session indicator and
   contribution/call-count telemetry. Existing provider fallback is retained.
6. Add full launch/resume/cancellation/concurrency regressions, paired latency
   and decision-quality audits, live native smoke, independent review and CI.
7. Merge/deploy only after that validation. Do not enable production cooperative
   mode as a side effect of this foundation commit.
