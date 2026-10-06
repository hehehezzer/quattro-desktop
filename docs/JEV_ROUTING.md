# Jev integration and host routing

The current provider contract is the model-authored,
[v2 decision interface](DYNAMIC_DECISIONS.md). Only
`quattro-jev-decisions-v2` envelopes are accepted. The executing native model
creates the question, alternatives, descriptions and relevant abstract
parameters for the decision it currently faces.

Initial request routing remains a local host responsibility. Bootstrap builds
and locks the execution plan using existing deterministic constraints and
verified registry availability. It does not contact Jev or synthesize a
question. Jev cannot select a provider, model, account, permission profile,
worker, or fallback route.

During native execution, `decision_capabilities` reports independently observed
capabilities. `operational_decision` evaluates the model's supplied alternatives
through the existing authenticated TypeSafe System One HTTPS route. A proposed
capability is usable only when the host independently confirms it; model text
cannot create availability or permission.

Provider failures, invalid content, unsupported capabilities, agent fallback,
and advice below the existing confidence floor return control to native
reasoning. Mandatory host checks and existing retry limits still apply.
Authored state is bounded and abstract; prompts, transcripts, code, paths,
commands, tool output and credentials must not be sent as decision content.

## Migration

The fixed routing questionnaire and v1 operational category API are removed.
Legacy requests fail validation before credential lookup or provider I/O;
there is no automatic translation into a generated-looking wrapper. Existing
routing settings do not restore a static provider questionnaire. Native
category settings are obsolete and reported as ignored.

Earlier PR #30/#31 routing measurements are retired historical evidence. Their
fixture agreement and routing latency do not demonstrate adoption, correctness
or performance of the current decision interface. See
[JEV_BENCHMARK.md](JEV_BENCHMARK.md) for current diagnostic requirements.
