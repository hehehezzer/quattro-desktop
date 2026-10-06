# Model-authored checkpoint decisions

Optional checkpoint guidance defaults off. New Pi sessions opt in with
`checkpointsEnabled: true` or `QUATTRO_JEV_CHECKPOINTS=1`; an explicit `=0`
disables it. Tool-result observations can request fresh native authorship.
They cannot create a provider question, choose a menu, execute a retry, grant
permission or certify validation. Existing action admission remains independent.

`decision_checkpoint.py` keeps bounded local evidence in a
`quattro-checkpoint-v2` envelope: opaque scope and policy identity, observed
revision, checkpoint event identifier, scalar observations and explicit
provenance. Observation parameter names are bounded abstract identifiers, not
an allowlist of decision features. Unknown observations remain unknown.
Externally supplied provenance is an agent assertion; it cannot attest the host.

A consultation requires an explicit `decision` using the canonical
`quattro-jev-decisions-v2` schema. The native model authors its question, option
ids, descriptions and relevant scalar context for the current decision. The
wrapper sends that validated content exactly. It does not derive decisions from
checkpoint event names or project local observations into provider parameters.
Scope identifiers, provenance, signatures, paths, copied evidence, prompts,
outputs and credentials stay outside provider decision content. Syntax checks
are defense in depth; the author must summarize abstractly.

Missing, legacy or malformed authored decisions produce
`native_authorship_required`, `called: false` and
`provider_attempt: NOT_ATTEMPTED` before the evaluator runs. The public authoring
schema advertises v2 only. The `after_inspection` and `failure_no_progress`
tracker events describe observed tool results, rather than decision categories
or a guarantee that evidence is sufficient. No automatic checkpoint consultation
is claimed for Codex or Pi tool-result callbacks.

Checkpoint consultation always uses fresh, uncached advice. The authored state
revision must match the local envelope. A trusted host tracker can check its
revision before and after consultation; cancellation and failed freshness
checks discard advice. These event checks do not establish exhaustive filesystem
freshness. Explicit native envelopes alone cannot prove independent host state.
Host capability attestations are separate function arguments, never JSON grants.
Unavailable tools and RTK remain unavailable even when authored context claims
otherwise. Constraint checks and host tool admission remain enforceable.

Acceptance requires a supplied option, verified choice evidence, a confirmed
provider attempt, confidence at least 0.90 and independent host effect checks.
Agent fallback and uncertainty return to native reasoning. Recommendations name
an integration effect and remain advice. Acceptance, delivery, admission,
receipt consumption, observed execution and task validation are separate facts;
this wrapper never marks application or task validation as true. Authored option
ids are omitted from checkpoint telemetry.

`DecisionSession` retains its 64-consultation budget, single-flight admission,
deadlines, cancellation, cooldown and strict response validation. Worker launch
or dispatch alone is not proof of a provider attempt. Lost responses may leave
attempt evidence unknown. Credentials remain in their existing native stores.

## Verification

`tests/test_decision_checkpoint.py` exercises explicit authored decisions,
legacy rejection before I/O, distinct questions and parameters, bounded local
observations, host capabilities, stale state, cancellation, uncertainty and
truthful evidence. Optional `tests/test_pi_checkpoints.py` uses an audited local
Pi dependency bundle to exercise actual extension callbacks. It starts no native
model and makes no provider requests; callbacks only provide authoring guidance.

`python scripts/benchmark_checkpoints.py --pairs 30 --output REPORT.json`
compares three synthetic fixture arms across six experimental scenarios. Its
questions and choices are test inputs, not production menus or observed model
authorship. Fixture time is not provider RTT, task performance or evidence of
benefit. Provider calls, actual task correctness, cost and native model reliance
remain unmeasured. Real matched task experiments need separately scoped approval.

Deploy paired native and host contracts together, preserve active session
ownership and reload only coordinated idle sessions. Rollback disables optional
checkpoint guidance and restores a compatible code bundle while preserving
mandatory action admission and completion evidence checks.
