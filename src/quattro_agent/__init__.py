"""Durable, host-controlled core primitives for the Quattro agent harness.

This package is intentionally independent from the legacy ``quattro-agent``
entry point.  It provides the storage, policy, workflow, validation, adapter,
and process-supervision contracts needed for a later compatibility migration.
Only OpenAI Codex and Pi are valid agent runtimes.
"""

__version__ = "0.2.0"

from .adapters import CodexAdapter, PiAdapter, adapter_for
from .delegation import (
    DelegationDecision, TaskDelegationDecision, classify_task_request,
    decide_delegation, select_execution_agent,
)
from .config import CURRENT_AI_CONFIG_VERSION, load_ai_config, migrate_ai_config, validate_ai_config
from .models import RunState, TaskState
from .policy import PolicyProfile, policy_profile
from .omniroute import (
    OmniRouteContract, OmniRouteRoutingMode, omniroute_routing_mode,
    validate_catalog_parity, validate_omniroute_contract,
)
from .sessions import prepare_shared_session_namespace
from .store import TaskStore
from .retrieval import ContextAssembler, QueryRouter, RepositoryIndexer, RetrievalStore
from .mandatory_context import (
    MandatoryContext,
    ProjectDestination,
    WorktreeClassification,
    WorktreeInspection,
    build_mandatory_context,
    inspect_worktree,
    resolve_project_destination,
)
from .collaboration import ProjectIdentity, RepositoryCoordinator, canonical_project
from .model_registry import (
    ContextDecision, ExecutionPlan, ExecutionTarget, ModelTarget, build_execution_plan,
    fallback_execution_plan, default_policy_path, load_model_registry,
    execution_target_for_route, select_execution_target, target_matches_actual,
)

__all__ = [
    "CURRENT_AI_CONFIG_VERSION",
    "CodexAdapter",
    "PiAdapter",
    "DelegationDecision",
    "TaskDelegationDecision",
    "classify_task_request",
    "select_execution_agent",
    "decide_delegation",
    "PolicyProfile",
    "OmniRouteContract",
    "OmniRouteRoutingMode",
    "omniroute_routing_mode",
    "RunState",
    "TaskState",
    "TaskStore",
    "ContextAssembler",
    "QueryRouter",
    "RepositoryIndexer",
    "RetrievalStore",
    "MandatoryContext",
    "ProjectDestination",
    "WorktreeClassification",
    "WorktreeInspection",
    "ProjectIdentity",
    "RepositoryCoordinator",
    "adapter_for",
    "build_mandatory_context",
    "inspect_worktree",
    "canonical_project",
    "load_ai_config",
    "migrate_ai_config",
    "policy_profile",
    "prepare_shared_session_namespace",
    "resolve_project_destination",
    "validate_omniroute_contract",
    "validate_catalog_parity",
    "validate_ai_config",
    "ExecutionTarget",
    "ExecutionPlan",
    "ContextDecision",
    "ModelTarget",
    "default_policy_path",
    "load_model_registry",
    "execution_target_for_route",
    "select_execution_target",
    "build_execution_plan",
    "fallback_execution_plan",
    "target_matches_actual",
]

from .routing import (
    RoutingDecision, RoutingTier, automatic_model_override, classify_pre_routing, classify_request,
    context_budget_tokens, deescalate_for_follow_up, effective_reasoning_effort,
    next_exceptional_effort, next_tier,
)
