"""Parent/child workflow DAG, dependency, readiness, and join primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping

from .errors import WorkflowError
from .models import TaskState
from .policy import PolicyProfile
from .store import SUPPORTED_AGENTS, TaskStore


@dataclass(frozen=True, slots=True)
class WorkflowNode:
    name: str
    title: str
    agent: str
    policy: PolicyProfile
    dependencies: tuple[str, ...] = ()
    display_metadata: Mapping[str, Any] = field(default_factory=dict)
    private_payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.agent not in SUPPORTED_AGENTS:
            raise WorkflowError(f"unsupported workflow agent: {self.agent}")
        if not self.name or len(self.name) > 100:
            raise WorkflowError("workflow node name must contain 1-100 characters")


@dataclass(frozen=True, slots=True)
class WorkflowDefinition:
    name: str
    nodes: tuple[WorkflowNode, ...]

    def validate(self) -> None:
        if not self.name or len(self.name) > 100:
            raise WorkflowError("workflow name must contain 1-100 characters")
        by_name = {node.name: node for node in self.nodes}
        if len(by_name) != len(self.nodes):
            raise WorkflowError("workflow node names must be unique")
        for node in self.nodes:
            unknown = set(node.dependencies) - set(by_name)
            if unknown:
                raise WorkflowError(
                    f"node {node.name} has unknown dependencies: {', '.join(sorted(unknown))}"
                )
            if node.name in node.dependencies:
                raise WorkflowError(f"node {node.name} depends on itself")
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(name: str) -> None:
            if name in visiting:
                raise WorkflowError("workflow dependency graph contains a cycle")
            if name in visited:
                return
            visiting.add(name)
            for dependency in by_name[name].dependencies:
                visit(dependency)
            visiting.remove(name)
            visited.add(name)

        for name in by_name:
            visit(name)


class JoinStatus(StrEnum):
    WAITING = "waiting"
    READY_TO_VALIDATE = "ready_to_validate"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class JoinResult:
    status: JoinStatus
    completed: int
    total: int
    failed_task_ids: tuple[str, ...] = ()


class WorkflowEngine:
    def __init__(self, store: TaskStore) -> None:
        self.store = store

    def spawn_child(
        self,
        parent_task_id: str,
        *,
        workflow: str,
        agent: str,
        title: str,
        policy: PolicyProfile,
        project_path: str | Path | None = None,
        display_metadata: Mapping[str, Any] | None = None,
        private_payload: Mapping[str, Any] | None = None,
        priority: int | None = None,
    ) -> str:
        parent = self.store.get_task(parent_task_id)
        return self.store.create_task(
            parent_task_id=parent_task_id,
            workflow=workflow,
            agent=agent,
            project_path=project_path or parent["project_path"],
            display_title=title,
            policy=policy,
            display_metadata=display_metadata,
            private_payload=private_payload,
            priority=parent["priority"] if priority is None else priority,
        )

    def instantiate(
        self,
        definition: WorkflowDefinition,
        *,
        parent_task_id: str,
        project_path: str | Path | None = None,
    ) -> dict[str, str]:
        definition.validate()
        identifiers: dict[str, str] = {}
        for node in definition.nodes:
            identifiers[node.name] = self.spawn_child(
                parent_task_id,
                workflow=definition.name,
                agent=node.agent,
                title=node.title,
                policy=node.policy,
                project_path=project_path,
                display_metadata=node.display_metadata,
                private_payload=node.private_payload,
            )
        for node in definition.nodes:
            for dependency in node.dependencies:
                self.store.add_dependency(identifiers[node.name], identifiers[dependency])
        return identifiers

    def dependencies_satisfied(self, task_id: str) -> bool:
        states = self.store.dependency_states(task_id)
        return all(state is TaskState.SUCCEEDED for state in states.values())

    def queue_ready_children(self, parent_task_id: str) -> tuple[str, ...]:
        ready: list[str] = []
        for child in self.store.children(parent_task_id):
            task_id = child["taskId"]
            if TaskState(child["state"]) is TaskState.CREATED and self.dependencies_satisfied(task_id):
                self.store.transition_task(task_id, TaskState.QUEUED)
                ready.append(task_id)
        return tuple(ready)

    def join_children(self, parent_task_id: str) -> JoinResult:
        parent = self.store.get_task(parent_task_id)
        parent_state = TaskState(parent["state"])
        children = self.store.children(parent_task_id)
        if not children:
            raise WorkflowError("cannot join a parent with no child tasks")
        failed_states = {
            TaskState.FAILED, TaskState.CANCELLED, TaskState.TIMED_OUT,
            TaskState.INTERRUPTED, TaskState.BLOCKED,
        }
        failed = tuple(
            child["taskId"] for child in children if TaskState(child["state"]) in failed_states
        )
        succeeded = sum(TaskState(child["state"]) is TaskState.SUCCEEDED for child in children)
        if failed:
            if parent_state is TaskState.WAITING_ON_CHILDREN:
                self.store.transition_task(
                    parent_task_id, TaskState.BLOCKED,
                    terminal_code="child_failed",
                    terminal_summary="One or more child tasks did not succeed.",
                )
            return JoinResult(JoinStatus.BLOCKED, succeeded, len(children), failed)
        if succeeded == len(children):
            if parent_state is TaskState.WAITING_ON_CHILDREN:
                self.store.transition_task(parent_task_id, TaskState.VALIDATING_RESULT)
            return JoinResult(JoinStatus.READY_TO_VALIDATE, succeeded, len(children))
        return JoinResult(JoinStatus.WAITING, succeeded, len(children))
