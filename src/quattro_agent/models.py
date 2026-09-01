"""Lifecycle models and transition rules for durable tasks and runs."""

from __future__ import annotations

import datetime as dt
from enum import StrEnum

from .errors import StateTransitionError


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")


class TaskState(StrEnum):
    CREATED = "created"
    QUEUED = "queued"
    VALIDATING = "validating"
    AWAITING_APPROVAL = "awaiting_approval"
    READY = "ready"
    RUNNING = "running"
    WAITING_ON_CHILDREN = "waiting_on_children"
    VALIDATING_RESULT = "validating_result"
    BLOCKED = "blocked"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    INTERRUPTED = "interrupted"


class RunState(StrEnum):
    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    INTERRUPTED = "interrupted"


class StepState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    NOT_RUN = "not_run"
    CANCELLED = "cancelled"


TERMINAL_TASK_STATES = frozenset({
    TaskState.SUCCEEDED,
    TaskState.FAILED,
    TaskState.CANCELLED,
    TaskState.TIMED_OUT,
    TaskState.INTERRUPTED,
})

RETRYABLE_TASK_STATES = frozenset({
    TaskState.FAILED,
    TaskState.TIMED_OUT,
    TaskState.INTERRUPTED,
})

TASK_TRANSITIONS: dict[TaskState, frozenset[TaskState]] = {
    TaskState.CREATED: frozenset({TaskState.QUEUED, TaskState.CANCELLED, TaskState.FAILED}),
    TaskState.QUEUED: frozenset({
        TaskState.VALIDATING, TaskState.AWAITING_APPROVAL, TaskState.READY,
        TaskState.RUNNING, TaskState.BLOCKED, TaskState.CANCELLING,
        TaskState.CANCELLED, TaskState.FAILED,
    }),
    TaskState.VALIDATING: frozenset({
        TaskState.AWAITING_APPROVAL, TaskState.READY, TaskState.BLOCKED,
        TaskState.CANCELLING, TaskState.FAILED,
    }),
    TaskState.AWAITING_APPROVAL: frozenset({
        TaskState.READY, TaskState.BLOCKED, TaskState.CANCELLED, TaskState.FAILED,
    }),
    TaskState.READY: frozenset({
        TaskState.RUNNING, TaskState.WAITING_ON_CHILDREN, TaskState.BLOCKED,
        TaskState.CANCELLING, TaskState.CANCELLED, TaskState.FAILED,
    }),
    TaskState.RUNNING: frozenset({
        TaskState.WAITING_ON_CHILDREN, TaskState.VALIDATING_RESULT,
        TaskState.AWAITING_APPROVAL, TaskState.BLOCKED, TaskState.CANCELLING,
        TaskState.SUCCEEDED, TaskState.FAILED, TaskState.TIMED_OUT,
        TaskState.INTERRUPTED,
    }),
    TaskState.WAITING_ON_CHILDREN: frozenset({
        TaskState.RUNNING, TaskState.VALIDATING_RESULT, TaskState.BLOCKED,
        TaskState.CANCELLING, TaskState.CANCELLED, TaskState.FAILED,
    }),
    TaskState.VALIDATING_RESULT: frozenset({
        TaskState.SUCCEEDED, TaskState.FAILED, TaskState.BLOCKED,
        TaskState.CANCELLING, TaskState.TIMED_OUT, TaskState.INTERRUPTED,
    }),
    TaskState.BLOCKED: frozenset({
        TaskState.QUEUED, TaskState.AWAITING_APPROVAL, TaskState.READY,
        TaskState.CANCELLED, TaskState.FAILED,
    }),
    TaskState.CANCELLING: frozenset({
        TaskState.CANCELLED, TaskState.FAILED, TaskState.TIMED_OUT,
        TaskState.INTERRUPTED,
    }),
    TaskState.FAILED: frozenset({TaskState.QUEUED, TaskState.CANCELLED}),
    TaskState.TIMED_OUT: frozenset({TaskState.QUEUED, TaskState.CANCELLED}),
    TaskState.INTERRUPTED: frozenset({TaskState.QUEUED, TaskState.CANCELLED, TaskState.FAILED}),
    TaskState.SUCCEEDED: frozenset(),
    TaskState.CANCELLED: frozenset(),
}

RUN_TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    RunState.CREATED: frozenset({RunState.STARTING, RunState.CANCELLED, RunState.FAILED}),
    RunState.STARTING: frozenset({RunState.RUNNING, RunState.CANCELLED, RunState.FAILED, RunState.INTERRUPTED}),
    RunState.RUNNING: frozenset({
        RunState.CANCELLING, RunState.CANCELLED, RunState.SUCCEEDED,
        RunState.FAILED, RunState.TIMED_OUT, RunState.INTERRUPTED,
    }),
    RunState.CANCELLING: frozenset({
        RunState.CANCELLED, RunState.FAILED, RunState.TIMED_OUT, RunState.INTERRUPTED,
    }),
    RunState.FAILED: frozenset(),
    RunState.TIMED_OUT: frozenset(),
    RunState.INTERRUPTED: frozenset(),
    RunState.CANCELLED: frozenset(),
    RunState.SUCCEEDED: frozenset(),
}

STEP_TRANSITIONS: dict[StepState, frozenset[StepState]] = {
    StepState.PENDING: frozenset({StepState.RUNNING, StepState.NOT_RUN, StepState.CANCELLED, StepState.BLOCKED}),
    StepState.RUNNING: frozenset({StepState.PASSED, StepState.FAILED, StepState.BLOCKED, StepState.CANCELLED}),
    StepState.BLOCKED: frozenset({StepState.PENDING, StepState.NOT_RUN, StepState.CANCELLED}),
    StepState.PASSED: frozenset(),
    StepState.FAILED: frozenset(),
    StepState.NOT_RUN: frozenset(),
    StepState.CANCELLED: frozenset(),
}


def _transition(current: StrEnum, target: StrEnum, table: dict, kind: str) -> None:
    if target == current:
        raise StateTransitionError(f"{kind} is already {target.value}")
    if target not in table[current]:
        raise StateTransitionError(
            f"invalid {kind} transition: {current.value} -> {target.value}"
        )


def ensure_task_transition(current: TaskState, target: TaskState) -> None:
    _transition(current, target, TASK_TRANSITIONS, "task")


def ensure_run_transition(current: RunState, target: RunState) -> None:
    _transition(current, target, RUN_TRANSITIONS, "run")


def ensure_step_transition(current: StepState, target: StepState) -> None:
    _transition(current, target, STEP_TRANSITIONS, "step")
