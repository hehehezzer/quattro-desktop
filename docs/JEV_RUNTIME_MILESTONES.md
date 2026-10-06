# Runtime milestones and mandatory validation

The current decision interface is
[model-authored v2 advice](DYNAMIC_DECISIONS.md). Meaningful changes in evidence
can prompt the executing native model to author a fresh question and alternatives
for planning, context, verification, recovery or the next action. Host milestone
handlers do not synthesize provider questions.

## Required host validation

The host constructs its existing required validator closures after native
execution and receipt checks. `run_validation_milestone` runs every selected
check once in the original host order. It preserves cancellation and bounded
command ownership. A provider answer cannot add, omit, retry, parallelize or
certify mandatory validators.

Historical experiment arguments remain readable where needed for compatibility,
but do not start provider work or reorder checks. Telemetry marks the static
questionnaire as retired and records passthrough behavior. No hidden provider
consultation or avoided model turn is inferred at this boundary.

Native Pi's optional existing result-checkpoint setting can supply a bounded
changed-evidence reminder to the execution model. It does not submit source,
output or a fixed questionnaire. Direct Codex's supported decision boundary is
its callable MCP tool; observing tool/turn events does not imply permission or
complete native-tool interception.

Managed failures, retry ceilings, sandbox policy, approved workers, account/model
selection, locked receipts and terminal success remain deterministic host
responsibilities. Native execution can ask for advice within those restrictions,
but generated content cannot expand them.

## Retired milestone evidence

The earlier host validation-order and continuation experiments are retired.
Aggregate records remain historical:

- [Milestone summary](../benchmarks/jev-pr31-milestone-summary.json).
- [Milestone component](../benchmarks/jev-pr31-milestone-component.json).
- [Milestone tasks](../benchmarks/jev-pr31-milestone-tasks.json).
- [Continuation component](../benchmarks/jev-pr31-continuation-component.json).
- [Continuation tasks](../benchmarks/jev-pr31-continuation-tasks.json).

Those experiments used obsolete fixed questionnaires. Their timing, fallback
and ordering results do not establish usefulness, live adoption or deployment
of the v2 interface. Required checks remain the completion evidence.
