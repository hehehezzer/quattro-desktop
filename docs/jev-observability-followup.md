# Jev rejection evidence follow-up (local source only)

Operational results now preserve `provider_selected_option`,
`provider_confidence`, `acceptance_threshold`, `provider_evidence` and
`rejection_reason` separately from the host `recommendation`, acceptance and
application fields. Missing or invalid provider metadata is `UNKNOWN`.
Only finite confidence in [0,1] and validated choice/evidence enums are kept.
No raw provider text, prompt, code, path, probability table or output is added
to these records.

DecisionSession now retains the validated provider choice even when its host
policy rejects it; otherwise a choice of `agent` and a low-confidence choice
were indistinguishable after the selected action was cleared. The wrapper
distinguishes timeout, delegation to agent, low confidence, provider
uncertainty, provider denial/fallback and malformed output. Cache/cooldown
events retain the original rejection reason without claiming a new call.
Accepted advice alone remains `applied=false`; application is recorded only
at the existing observable host boundary.

The old 607.7 ms smoke result still has unknown selected option, confidence
and rejection cause. Its generic `uncertain` label cannot establish a specific
provider cause retrospectively. No new live call was made in this follow-up.

## Useful categorical task state

The smoke request supplied only multi-step, modifications required and context
missing booleans, with inspection phase and no previous result. It did not
describe the actual implementation or validation milestone.

The already supported explicit native `operational_decision` request can use
`execution_state.phase` = inspection/implementation/validation/completion,
bounded attempt/revision, and `previous_result` = none/success/transient_failure/
test_failure/unknown_failure. Existing boolean fields include tests_available,
changes_present, verification_required, context_missing, independent_steps,
repository_required and retrieval_required.

Populate these from actual host observations: for example, observed edits and
a failed mandatory test can justify changes_present=true, tests_available=true,
verification_required=true, phase=validation and previous_result=test_failure.
No failed-test text or code needs to leave the host. A locally known missing
evidence question can set context_missing=true. Do not infer semantic evidence
sufficiency merely from nonempty retrieval or successful test counts.
`task` still uses the original three-flag fixture; its hardcoded inspection phase
was not silently expanded by this observability patch.

## Installation required, not performed

- Copy reviewed Quattro source `decision_service.py` and `operational_advice.py`
  to their existing installed module locations.
- Restart the broker to load its local source updates in broker.py, usage.py and
  operational_advice.py. Existing owner/channel/project grants stay unchanged.
- New native helper/MCP/Pi sessions load the new module metadata. Leave running
  coding work intact; reload only through a supported idle-session action.

No flag, credential, subscription, access-scope or activation change is needed.
This follow-up has not installed modules or restarted services.
