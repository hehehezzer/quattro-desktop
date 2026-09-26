# PR #30 repair validation

Production default remains **OFF**. This is not cooperative promotion.

## Reconciled launcher fix

Commit `6af8f96` follows published `195e7af` on the same branch. Codex remote
frontends reject `--add-dir`; the fix places those roots on the app-server's
`sandbox_workspace_write.writable_roots`, mirrors explicit sandbox/approval
policy, and preserves developer instructions. The native frontend remains
Codex, not a Quattro conversation replacement. The commit and its tests are
included in this PR rather than left as an installed-only patch.

## Confirmed findings repaired

- Benchmark target unavailability is an outcome for both entrypoints.
- Fast-guard/off placeholders no longer suppress existing harness shadow ML
  prediction. Native fast paths still do not add learned inference.
- Decision-feature complexity, explicit targets and tier ceilings are checked
  before starting optional Jev work.
- Credential detection is separate from control normalization/truncation;
  URL, bearer and assignment-shaped secrets remain protected, including secrets
  beyond retained telemetry length.
- Low complexity uses the enum's actual lowercase value.
- Pre-routing failure rolls back a new reservation or finalizes resumed
  coordination. Children do not finalize a borrowed parent reservation.
  Cleanup failures cannot replace the original error. Passthrough credential
  lookups are rejected before reserving capacity; explicit legacy behavior is
  unchanged.
- Benchmark ordering rotates and reverses deterministically over six orders;
  the JSON records each repetition's order. No random benchmark ordering.

No published finding was rejected. Tests previously relying on the broken
low-complexity guard now use genuinely eligible debugging/ambiguous tasks.

## Fresh local validation

- `python -m unittest discover -s tests -p 'test_jev.py'`: 37 passed.
- `python -m unittest discover -s tests -p 'test_unified_routing.py'`: 20 passed.
- `python -m unittest discover -s tests -p 'test_codex_turn_bridge.py'`: 14 passed.
- `python -m unittest discover -s tests -p 'test_*.py'`: 699 run, 5 platform
  skips, no failures. Includes native launcher, Pi, durability, cancellation,
  concurrency and telemetry coverage.
- Compileall, Python hygiene, public-artifact policy and whitespace checks pass.
- Independent read-only Codex review of repairs: no actionable defects; its
  attempted tests were sandbox-blocked. Full suite above ran separately.

## Balanced simulated benchmark

Commands: `python scripts/benchmark_jev.py [--native] --repetitions 24`.
Each entrypoint/mode has 288 samples; total 1,728. Real child lifecycle with
**simulated** 20 ms evaluations, no external provider and no active learned
artifact. These are routing measurements, not first-token or execution times.

| Entrypoint | Mode | p50 ms | p95 ms |
|---|---|---:|---:|
| Harness | OFF | 0.479 | 0.602 |
| Harness | SHADOW | 0.477 | 0.674 |
| Harness | COOPERATIVE | 0.475 | 59.134 |
| Native | OFF | 0.623 | 0.795 |
| Native | SHADOW | 0.637 | 0.821 |
| Native | COOPERATIVE | 0.643 | 60.037 |

Each enabled mode/entrypoint starts 24 evaluations in 288 turns after repaired
eligibility checks. Cooperative fusion p50/p95: 0.008/0.010 ms. The fixture
selects the same model distribution in all modes. This does not establish live
quality, pricing, promotion readiness, or an improvement over PR #29.

## Live provider gate

Runtime environment presence-only check: `TYPESAFE_API_KEY` unavailable.
LIVE JEV VALIDATION: BLOCKED — TYPESAFE_API_KEY unavailable.
No credential values inspected, retained or requested. Merge/deployment with
OFF default is permitted by the release owner; cooperative promotion remains
subject to the separate documented evidence gates.
