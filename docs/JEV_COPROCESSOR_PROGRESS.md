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
5. Add bounded failure cooldown, warning-once behavior, session indicator,
   contribution/call-count telemetry and unavailable-provider fallback.
6. Add full launch/resume/cancellation/concurrency regressions, paired latency
   and decision-quality audits, live native smoke, independent review and CI.
7. Merge/deploy only after that validation. Do not enable production cooperative
   mode as a side effect of this foundation commit.
