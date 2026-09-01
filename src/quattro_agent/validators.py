"""Reusable evidence-gate result contracts for harness workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, Sequence

from .privacy import display_text


class ValidationStatus(StrEnum):
    PASSED = "Passed"
    FAILED = "Failed"
    BLOCKED = "Blocked"
    NOT_RUN = "Not Run"


@dataclass(frozen=True, slots=True)
class ValidationResult:
    validator: str
    status: ValidationStatus
    summary: str
    command: str | None = None
    artifact_ids: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    duration_seconds: float | None = None

    def __post_init__(self) -> None:
        display_text(self.validator, field="validator", maximum=100)
        display_text(self.summary, field="validation_summary", maximum=1_000)
        if self.command is not None:
            display_text(self.command, field="validation_command", maximum=2_000)
        for item in (*self.artifact_ids, *self.evidence):
            display_text(item, field="validation_evidence", maximum=1_000)
        if self.duration_seconds is not None and self.duration_seconds < 0:
            raise ValueError("validation duration cannot be negative")

    def display_dict(self) -> dict[str, object]:
        return {
            "validator": self.validator,
            "status": self.status.value,
            "summary": self.summary,
            "command": self.command,
            "artifactIds": list(self.artifact_ids),
            "evidence": list(self.evidence),
            "durationSeconds": self.duration_seconds,
        }


class Validator(Protocol):
    name: str

    def validate(self) -> ValidationResult: ...


@dataclass(frozen=True, slots=True)
class ValidationSummary:
    status: ValidationStatus
    results: tuple[ValidationResult, ...] = field(default_factory=tuple)


def aggregate_validation(results: Sequence[ValidationResult]) -> ValidationSummary:
    values = tuple(results)
    if any(result.status is ValidationStatus.FAILED for result in values):
        status = ValidationStatus.FAILED
    elif any(result.status is ValidationStatus.BLOCKED for result in values):
        status = ValidationStatus.BLOCKED
    elif not values or all(result.status is ValidationStatus.NOT_RUN for result in values):
        status = ValidationStatus.NOT_RUN
    elif any(result.status is ValidationStatus.NOT_RUN for result in values):
        status = ValidationStatus.BLOCKED
    else:
        status = ValidationStatus.PASSED
    return ValidationSummary(status=status, results=values)
