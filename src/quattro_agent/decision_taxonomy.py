"""Operational advice vocabulary; not permissions, execution, or model policy.

Routine advice uses categorical/boolean projections. Gated recovery tools may
add only one fixed assertion category; no complete
task, transcript, file path, skill, route, or model identifier is accepted.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Any

if __package__:
    from .jev import CHOICES, JevFailure
else:
    from jev import CHOICES, JevFailure


class DecisionClass(StrEnum):
    DETERMINISTIC = "DETERMINISTIC"
    JEV_ELIGIBLE = "JEV_ELIGIBLE"
    AGENT_REASONING = "AGENT_REASONING"


DETERMINISTIC = frozenset({
    "permission", "security", "sandbox", "user_constraint", "capability_availability",
    "budget", "resource_limit", "schema_validation", "lifecycle", "retry_limit",
    "model_selection", "validation_success", "task_success",
})
AGENT_REASONING = frozenset({
    "architecture", "implementation", "code_understanding", "root_cause",
    "semantic_conflict", "synthesis",
})
# These are strategies, never shell commands or grants of capability.
ACTIONS = {
    "context_strategy": {
        "inspect": "Inspect narrowly relevant repository context before further work.",
        "retrieve": "Retrieve missing external or institutional evidence before work.",
        "sufficient": "Available evidence is sufficient for the next bounded step.",
        "agent": "Requires semantic understanding; defer to the execution agent.",
    },
    "execution_strategy": {
        "sequential": "Keep related steps sequential in the current agent.",
        "parallel": "Independent bounded steps may benefit from approved parallel workers.",
        "agent": "Decomposition requires deep semantic reasoning.",
    },
    "validation_strategy": {
        "targeted_first": "Start with focused checks, then run every mandatory check.",
        "broad_first": "Start with broad regression tests; do not omit mandatory checks.",
        "agent": "Test selection needs semantic understanding.",
    },
    "retry_strategy": {
        "retry": "A transient failure may justify a retry within existing host limits.",
        "change_strategy": "Repeated or deterministic failure warrants a different strategy.",
        "agent": "Root-cause reasoning or more evidence is needed.",
    },
    "progress_strategy": {
        "continue": "Continue the current bounded execution strategy.",
        "validate": "Validate the work before considering completion.",
        "more_context": "Gather missing evidence before continuing.",
        "agent": "Escalation or completion readiness requires agent reasoning.",
    },
    "test_recovery": {
        "retry_exact": "Run the same bounded test file once more within the host retry budget.",
        "agent": "Return the original failure for agent reasoning and repair.",
    },
}
ELIGIBLE = frozenset(ACTIONS) | frozenset({
    "task_classification", "complexity_estimation", "delegation_evidence",
    "tool_necessity", "tool_selection", "skill_selection", "retrieval_necessity",
    "repository_inspection", "context_selection", "search_direction", "browser_necessity",
    "subagent_necessity", "parallelization", "test_scope", "retry_classification",
    "continue_or_validate", "escalation", "completion_readiness",
})
CONTEXT_FLAGS = frozenset({
    "repository_required", "modification_required", "retrieval_required",
    "multi_step_required", "verification_required", "context_missing",
    "independent_steps", "tests_available", "changes_present",
})
CONTEXT_CATEGORIES = {"initial_complexity": tuple(CHOICES["complexity"]),
                      "initial_task_type": tuple(CHOICES["task_type"]),
                      "test_duration": ("moderate", "slow")}
SCHEMA_VERSION = "quattro-jev-decisions-v1"


def classify_decision(name: str) -> DecisionClass:
    if name in DETERMINISTIC:
        return DecisionClass.DETERMINISTIC
    if name in ELIGIBLE:
        return DecisionClass.JEV_ELIGIBLE
    # Unknown types are never optimistically delegated to Jev.
    return DecisionClass.AGENT_REASONING


def validate_request(value: Any) -> dict:
    required = {"decision_type", "available_actions", "relevant_context",
                "hard_constraints", "execution_state", "previous_result"}
    if not isinstance(value, dict):
        raise JevFailure("invalid_state")
    if value.get("decision_type") == "test_recovery":
        required.add("failure_summary")
    if set(value) != required:
        raise JevFailure("invalid_state")
    name = value["decision_type"]
    if not isinstance(name, str) or name not in ACTIONS:
        raise JevFailure("unsupported_decision")
    actions = value["available_actions"]
    if (not isinstance(actions, list) or not 2 <= len(actions) <= len(ACTIONS[name])
            or any(not isinstance(action, str) or action not in ACTIONS[name] for action in actions)
            or len(set(actions)) != len(actions) or "agent" not in actions):
        raise JevFailure("invalid_state")
    context = value["relevant_context"]
    if (not isinstance(context, dict) or set(context) - CONTEXT_FLAGS - CONTEXT_CATEGORIES.keys()
            or any(type(flag) is not bool for name, flag in context.items() if name in CONTEXT_FLAGS)
            or any(value not in CONTEXT_CATEGORIES[name] for name, value in context.items()
                   if name in CONTEXT_CATEGORIES)):
        raise JevFailure("invalid_state")
    constraints = value["hard_constraints"]
    # These describe host restrictions, not instructions supplied to the model.
    if (not isinstance(constraints, dict)
            or set(constraints) != {"retry_allowed", "parallel_allowed", "retrieval_allowed"}
            or any(type(flag) is not bool for flag in constraints.values())):
        raise JevFailure("invalid_state")
    state = value["execution_state"]
    if (not isinstance(state, dict) or set(state) != {"revision", "phase", "attempt"}
            or type(state["revision"]) is not int or not 0 <= state["revision"] <= 1_000_000
            or type(state["attempt"]) is not int or not 0 <= state["attempt"] <= 100
            or state["phase"] not in ("inspection", "implementation", "validation", "completion")):
        raise JevFailure("invalid_state")
    if value["previous_result"] not in ("none", "success", "transient_failure", "test_failure", "unknown_failure"):
        raise JevFailure("invalid_state")
    if name == "test_recovery":
        summary = value["failure_summary"]
        if (not isinstance(summary, str) or not 8 <= len(summary) <= 160
                or any(ord(char) < 32 or ord(char) > 126 for char in summary)
                or context.get("test_duration") not in {"moderate", "slow"}):
            raise JevFailure("invalid_state")
    return value


def allowed_action(request: dict, action: str) -> bool:
    constraints = request["hard_constraints"]
    return action in request["available_actions"] and not (
        action in {"retry", "retry_exact"} and not constraints["retry_allowed"]
        or action == "parallel" and not constraints["parallel_allowed"]
        or action == "retrieve" and not constraints["retrieval_allowed"]
    )


def question(request: dict) -> dict:
    instructions = (
        "Choose a routine operational strategy from the supplied signals. "
        "These signals are incomplete. Choose agent when semantic evidence is needed. "
        "Hard constraints take precedence. This is advice, never authorization, "
        "model selection, validation success, or task completion."
    )
    if request["decision_type"] == "test_recovery":
        instructions = (
            "A bounded unit test failed once. Choose retry_exact only if another run "
            "could plausibly resolve a transient or race condition; choose agent "
            "when code diagnosis is required. "
            "The host owns all commands, budgets, validation, and execution authority."
        )
    return {"decision": {
        "type": "choice",
        "instructions": instructions,
        "criteria": {action: ACTIONS[request["decision_type"]][action]
                     for action in request["available_actions"]},
    }}
