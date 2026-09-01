# Orchestration flow

`quattro-agent prompt` classifies the raw request before creating a task.

## DIRECT

Explanations, recommendations, comparisons, and analysis that do not request
an action stay direct. The harness performs one bounded Responses request to
OmniRoute, optionally adding bounded retrieval context. No durable execution
task or Codex/Pi child is launched.

## DELEGATE

Repository changes, commands, tests, installations, migrations, and other
explicit execution requests become durable tasks. Quattro records a safe
display title, classification, agent, tier, policy, validation, and terminal
outcome. Prompt and output payloads stay private in the task store.

Codex is the primary execution runtime. Pi is used only for explicitly bounded
specialist work and is non-recursive. Subagents return evidence; the primary
orchestrator remains responsible for edits and validation.

## Failure behavior

Provider contract failures, unavailable runtimes, policy escalation, lease
conflicts, timeouts, cancellation, malformed output, and validation failures
are explicit task outcomes. Quattro does not silently switch an unavailable
provider into a fake success or copy credentials into a fallback path.
