# Bounded test invocation and model-authored recovery

Current recovery decisions use the
[v2 model-authored interface](DYNAMIC_DECISIONS.md). The bounded test helper
executes a selected existing test file once. It does not construct a fixed retry
question, contact Jev, or silently rerun a failed test.

`quattro_test` remains separately exposed by existing host policy. The tool
accepts a strict test basename, optionally prefixed by `tests/`, and rejects
absolute paths, symlinks and repository escapes. Python owns the interpreter,
argument vector, working directory, existing 20-second command bound and
16 KiB output ceiling. Linux process ownership/cleanup restrictions remain;
an unsupported platform does not acquire executable recovery capability.

A pass returns its bounded result. A failure returns the original failure and
indicates that native action is required. The executing model can inspect local
evidence and author a decision-specific question and alternatives through
`operational_decision`. Failure output, paths and source must not be copied into
the provider envelope.

Any subsequent retry requires existing host authorization and available budget.
An authored retry option never creates that permission. Jev's current advice
confidence floor is unchanged at 0.90 for all accepted v2 advice. Agent fallback,
uncertainty, unavailable capabilities and provider failure return control to
native reasoning. Provider POSTs are never automatically replayed.

A passing tool invocation does not certify task completion or remove mandatory
post-agent validation. Keep provider response validation, advice acceptance,
native delivery, test execution and task validation as separate evidence.

## Retired experiment

The earlier fixed two-choice recovery class, special recovery confidence rule,
automatic in-tool retry and matched fail-once experiment are retired. Their
historical observations concern an obsolete executable path and do not prove
current recovery usefulness or deployment. Historical recovery switches cannot
restore that provider questionnaire. Use current authored native acceptance
and existing host validation to assess the implementation.
