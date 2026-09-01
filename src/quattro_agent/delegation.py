"""Small, explicit Codex-to-Pi delegation policy and result contracts."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paths import omniroute_base_url


DELEGATION_KINDS = frozenset({"exploration", "implementation", "tests", "review", "security"})
PI_WORKER_PROVIDER = "omniroute"
PI_WORKER_MODEL = "auto"
PI_WORKER_BASE_URL = omniroute_base_url()

_SIMPLE = re.compile(
    r"(?i)\b(typo|spelling|rename one|single obvious|small edit|one[- ]line|"
    r"simple config(?:uration)?|change (?:a|one) value)\b"
)
_COMPLEX = re.compile(
    r"(?i)\b(explore|investigate|trace|locate|inventory|research|review|audit|"
    r"security|subsystem|independent|isolated|test(?:s|ing)?|multiple files|"
    r"repository|architecture|regression|root cause)\b"
)


@dataclass(frozen=True, slots=True)
class DelegationDecision:
    delegate: bool
    reason: str
    kind: str

    def to_dict(self) -> dict[str, Any]:
        return {"delegate": self.delegate, "reason": self.reason, "kind": self.kind}


@dataclass(frozen=True, slots=True)
class TaskDelegationDecision:
    """Quattro's pre-routing decision for a user request.

    This is intentionally separate from ``RoutingDecision``: routing chooses
    an OmniRoute requirement tier, while this gate decides whether Quattro
    must create an execution task at all.
    """

    decision: str
    reason: str
    confidence: float
    required_agent: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "reason": self.reason,
            "confidence": self.confidence,
            "requiredAgent": self.required_agent,
        }


def select_execution_agent(request: str, *, requested: str | None = None) -> str:
    """Choose the execution runtime without involving OmniRoute routing."""
    if requested in {"codex", "pi"}:
        return requested
    if re.search(r"(?i)\b(?:automation|automate|browser|long[- ]running|workflow)\b", request):
        return "pi"
    return "codex"


_EXECUTION = re.compile(
    r"(?i)\b(?:modify|edit|change|fix|implement|build|debug|test|deploy|run|execute|"
    r"inspect|investigate|repository|repo|browser|automate|automation|command|"
    r"terminal|migration|refactor|apply|install|configure|patch|validate)\b"
)
_DIRECT_OVERRIDE = re.compile(
    r"(?i)\b(?:explain|what is|how does|why does|documentation|docs?|brainstorm|"
    r"suggest|recommend|compare|analy[sz]e|summari[sz]e|snippet|example)\b"
)
_MUTATION = re.compile(
    r"(?i)\b(?:modify|edit|change|fix|implement|build|debug|apply|deploy|run|"
    r"execute|automate|install|patch|refactor|test(?:ing)?\s+(?:the|this|my|it))\b"
)


def classify_task_request(request: str, *, preferred_agent: str = "codex") -> TaskDelegationDecision:
    """Classify a raw user request before OmniRoute model selection.

    The classifier is lexical and deterministic. Analysis/explanation alone is
    direct; an explicit execution verb wins when paired with analysis words.
    """
    compact = " ".join(request.split())[:8_000]
    # Empty interactive/resume prompts are a valid launcher control request;
    # they are not user work to delegate.
    if not compact:
        return TaskDelegationDecision("DIRECT", "interactive_session_without_prompt", 1.0, None)
    if "\x00" in compact:
        raise ValueError("request must contain safe characters")
    agent = preferred_agent if preferred_agent in {"codex", "pi"} else "codex"
    # A requested recommendation is still direct even when its object is a
    # fix; only an explicit action verb changes the decision.
    if _DIRECT_OVERRIDE.search(compact) and not re.search(
        r"(?i)\b(?:apply|implement|modify|edit|change|deploy|run|execute|automate|install|patch)\b",
        compact,
    ):
        return TaskDelegationDecision("DIRECT", "request_can_be_answered_without_execution", 0.93, None)
    if _MUTATION.search(compact):
        return TaskDelegationDecision("DELEGATE", "request_requires_execution", 0.98, agent)
    if _EXECUTION.search(compact) and not _DIRECT_OVERRIDE.search(compact):
        return TaskDelegationDecision("DELEGATE", "request_requires_tools_or_repository_context", 0.94, agent)
    if _DIRECT_OVERRIDE.search(compact):
        return TaskDelegationDecision("DIRECT", "request_can_be_answered_without_execution", 0.93, None)
    return TaskDelegationDecision("DIRECT", "no_deterministic_execution_trigger", 0.70, None)


def decide_delegation(objective: str, kind: str) -> DelegationDecision:
    """Apply a conservative gate after Codex has identified a bounded work item."""
    bounded = objective.strip()
    if kind not in DELEGATION_KINDS:
        raise ValueError(f"unsupported delegation kind: {kind}")
    if not bounded or len(bounded) > 8_000 or "\x00" in bounded:
        raise ValueError("delegation objective must contain 1-8000 safe characters")
    if _SIMPLE.search(bounded):
        return DelegationDecision(False, "simple_direct_task", kind)
    if len(bounded.split()) < 6 and not _COMPLEX.search(bounded):
        return DelegationDecision(False, "insufficient_bounded_complexity", kind)
    if kind in {"exploration", "review", "security", "tests"}:
        return DelegationDecision(True, f"bounded_{kind}", kind)
    if _COMPLEX.search(bounded):
        return DelegationDecision(True, "isolated_implementation_analysis", kind)
    return DelegationDecision(False, "codex_direct_is_cheaper", kind)


def worker_prompt(objective: str, kind: str) -> str:
    return f"""You are a temporary Pi specialist working for a primary Codex session.

BOUNDED ROLE: {kind}
OBJECTIVE: {objective.strip()}

Use the supplied Quattro retrieval context and read-only tools only inside the repository.
Do not inspect credentials or unrelated home paths, do not make architectural or product
decisions, do not spawn workers, and do not retry failed work.
For implementation work, propose exact isolated edits for Codex to integrate; do not
claim that files changed unless the supplied context proves it. Escalate missing context.

Return only this compact contract (keep the whole response below 12000 characters):
STATUS
FINDINGS
FILES_CHANGED
VALIDATION
RISKS
NEXT_ACTION
"""


def codex_delegation_instructions(max_workers: int) -> str:
    return f"""Codex is the sole primary orchestrator. Keep simple edits, obvious bugs, and
small configuration changes in this session. When context isolation is materially useful,
delegate one bounded read-only specialist task with:
  quattro-agent delegate run --kind KIND --directory PATH --objective TEXT
Kinds: exploration, implementation, tests, review, security. Pi returns focused evidence or
an exact change proposal for Codex to integrate and validate; it does not own architecture or
final implementation. Never pass conversation transcripts or secrets. Use at most {max_workers}
concurrent Pi workers, normally one, never spawn recursively, and retry at most once only when
Codex can provide materially better context. If the policy declines delegation, work directly.
"""


def ensure_pi_worker_home(path: Path) -> Path:
    """Create a credential-free Pi runtime that routes only through local OmniRoute."""
    path = path.expanduser().resolve(strict=False)
    if path.exists() and path.is_symlink():
        raise OSError("Pi worker home must not be a symbolic link")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    models = {
        "providers": {
            PI_WORKER_PROVIDER: {
                "baseUrl": PI_WORKER_BASE_URL,
                "api": "openai-responses",
                # Pi requires a non-empty value for keyless local providers. This
                # sentinel is deliberately not a credential and must not be replaced
                # with a real secret; the local gateway ignores it.
                "apiKey": "quattro-local-only",
                "models": [{
                    "id": PI_WORKER_MODEL,
                    "name": "OmniRoute Auto",
                    "reasoning": True,
                    "input": ["text"],
                    "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                    "contextWindow": 200_000,
                    "maxTokens": 8_192,
                }],
            }
        }
    }
    settings = {"defaultProvider": PI_WORKER_PROVIDER, "defaultModel": PI_WORKER_MODEL}
    for name, value in (("models.json", models), ("settings.json", settings)):
        target = path / name
        if target.exists() and target.is_symlink():
            raise OSError(f"Pi worker {name} must not be a symbolic link")
        fd, temporary = tempfile.mkstemp(prefix=f".{name}.", dir=path)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(value, stream, separators=(",", ":"), sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, target)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
    return path


def compact_pi_json_output(payload: str, limit: int = 32_000) -> tuple[str, dict[str, Any]]:
    """Reduce Pi's JSON event stream to the final answer and safe usage telemetry."""
    final_text = ""
    telemetry: dict[str, Any] = {
        "provider": None, "model": None, "inputTokens": 0,
        "outputTokens": 0, "totalTokens": 0,
    }
    for raw in payload.splitlines():
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if event.get("type") not in {"message_end", "turn_end", "agent_end"}:
            continue
        message = event.get("message")
        if not isinstance(message, dict) and event.get("type") == "agent_end":
            messages = event.get("messages")
            message = messages[-1] if isinstance(messages, list) and messages else None
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        text_parts = [
            part.get("text", "") for part in message.get("content", [])
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        candidate = "".join(text_parts).strip()
        if candidate:
            final_text = candidate
        usage = message.get("usage") if isinstance(message.get("usage"), dict) else {}
        telemetry = {
            "provider": message.get("provider"),
            "model": message.get("model"),
            "inputTokens": int(usage.get("input", 0) or 0),
            "outputTokens": int(usage.get("output", 0) or 0),
            "totalTokens": int(usage.get("totalTokens", 0) or 0),
        }
    if not final_text:
        final_text = "STATUS\nFAILED\nFINDINGS\nPi returned no final answer.\nFILES_CHANGED\nNone\nVALIDATION\nNot Run\nRISKS\nWorker output was unavailable.\nNEXT_ACTION\nCodex should handle the task directly."
    required = ("STATUS", "FINDINGS", "FILES_CHANGED", "VALIDATION", "RISKS", "NEXT_ACTION")
    if not all(heading in final_text for heading in required):
        final_text = (
            "STATUS\nCOMPLETE\nFINDINGS\n" + final_text
            + "\nFILES_CHANGED\nNone reported\nVALIDATION\nNot Run\nRISKS\nContract normalized by Quattro."
            "\nNEXT_ACTION\nCodex must inspect and validate the finding."
        )
    encoded = final_text.encode("utf-8")
    if len(encoded) > limit:
        final_text = encoded[:limit].decode("utf-8", errors="ignore") + "\n[RESULT TRUNCATED]"
    return final_text.rstrip() + "\n", telemetry
