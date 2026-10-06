# Decision evidence and rejected advice

Current advice uses only the
[v2 model-authored interface](DYNAMIC_DECISIONS.md). Questions, option identifiers,
descriptions, phases and scalar context are authored for the current decision;
there is no phase, outcome, flag or category menu supplying provider questions.

Provider attempt, validated response, accepted advice, native delivery and actual
application must remain distinguishable. A session request count is not evidence
that a provider POST occurred. Confirmed transport evidence records the actual
attempt. Cache reuse is not a new call, and cooldown/disabled/invalid-input paths
do not manufacture provider evidence.

A rejected response can have a validated choice and confidence while still
failing host capability/constraint checks or the confidence floor. The response
can return the validated bounded result to the native model, but persistent
telemetry stores only sanitized stages, safety effects, confidence, timing and
fixed reasons. Authored identifiers, questions, context, descriptions and raw
provider bodies are excluded.

An accepted answer does not prove application. Pi can confirm supported tool-
result delivery; native model reliance remains unknown. Unobserved application
stays unverified. A subsequent successful native fallback action must not be
reported as an accepted Jev offload. Missing or unobserved evidence remains
unknown rather than being reconstructed from configuration or counters.

Local safety/progress guards are recorded as guard-only instrumentation with
no provider consultation. Their fixed thresholds and risk inputs enforce host
restrictions; they do not revive the obsolete provider questionnaire.

## Historical follow-up retired

The prior static-category rejection follow-up and smoke measurements are retired.
A generic historical uncertainty label cannot establish a specific old rejection
cause retrospectively. Those records neither verify v2 adoption nor authorize
installation, protected policy migration or an active-session restart. Current
rollout requires reviewed provenance, coordinated sessions and the existing
access/grant boundaries.
