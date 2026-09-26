"""TypeSafe System One contract. No execution policy or OmniRoute dependency."""
from __future__ import annotations

import http.client
import json
import math
import re
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any

SCHEMA_VERSION = "quattro-jev-routing-v1"
MODEL = "jev-latest"
BASE_URL = "https://api.typesafe.ai"
MAX_RESPONSE_BYTES = 32_768
# Frozen v1 wire vocabulary (not the broader training/probe vocabulary).
TASK_CATEGORIES = frozenset({
    "repository_modification", "repository_verification", "repository_inspection",
    "current_information_research", "external_research", "implementation", "verification",
    "tool_execution", "summarization", "drafting", "comparison", "reasoning", "explanation", "general",
})
FLAGS = (
    "repository_required", "modification_required", "tool_required",
    "retrieval_required", "current_information_required", "execution_required",
    "multi_step_required", "verification_required",
    "frontend", "security_sensitive", "debugging", "review",
)
CHOICES = {
    "execution": {"DIRECT": "Answer without external actions or retrieval.",
                  "DELEGATE": "Requires tools, repository work, retrieval or verification."},
    "complexity": {"LOW": "Simple single-step task.", "MEDIUM": "Bounded multi-step task.",
                   "HIGH": "Complex interacting requirements."},
    "task_type": {name: None for name in (
        "CODING", "RESEARCH", "GENERAL", "REASONING", "FRONTEND", "DEBUGGING", "REVIEW", "OTHER",
    )},
    "capability": {"CHEAP": "Minimal capability suffices.",
                     "STANDARD": "Normal engineering capability needed.",
                     "STRONG": "Strong reasoning capability needed.",
                     "FRONTIER": "Exceptional reasoning capability needed."},
}
QUESTIONS = {
    name: {"type": "choice", "instructions": f"Classify {name} from the requirement signals only.",
           "criteria": criteria}
    for name, criteria in CHOICES.items()
}


class JevFailure(Exception):
    """Only a fixed category, never provider bodies, URLs, or credentials."""

    def __init__(self, category: str):
        super().__init__(category)
        self.category = category


def serialize_state(request: str) -> str:
    """Discard text entirely; derive only bounded pre-decision requirement signals."""
    from .intelligence.features import extract_decision_features

    return serialize_features(extract_decision_features(request[:32_000]), request=request)


def serialize_features(requirements: Mapping[str, Any], *, request: str) -> str:
    """Project the canonical extraction without re-running requirement analysis."""
    text = request[:32_000]
    features = dict(requirements)
    features.update({name: bool(re.search(pattern, text, re.IGNORECASE)) for name, pattern in {
        "frontend": r"\b(?:frontend|front-end|css|html|ui|ux|react|accessibility)\b",
        "security_sensitive": r"\b(?:security|credentials?|authentication|authorization|secrets?)\b",
        "debugging": r"\b(?:debug|debugging|reproduce|root cause|regression)\b",
        "review": r"\b(?:review|audit|inspect)\b",
    }.items()})
    return json.dumps({
        "schema_version": SCHEMA_VERSION,
        **{name: features[name] for name in FLAGS},
        "complexity": features["complexity"],
        "category": features["category"],
        "task_category": features["task_category"],
    }, sort_keys=True, separators=(",", ":"), allow_nan=False)


def validate_state(state: Any) -> None:
    expected = {"schema_version", *FLAGS, "complexity", "category", "task_category"}
    if not isinstance(state, dict) or set(state) != expected:
        raise JevFailure("invalid_state")
    if (state["schema_version"] != SCHEMA_VERSION
            or any(type(state[name]) is not bool for name in FLAGS)
            or state["complexity"] not in ("low", "medium", "high")
            or state["category"] not in ("general", "coding", "research", "reasoning")
            or not isinstance(state["task_category"], str)
            or state["task_category"] not in TASK_CATEGORIES):
        raise JevFailure("invalid_state")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise JevFailure("invalid_json")
        result[name] = value
    return result


def decode(data: bytes) -> Any:
    try:
        return json.loads(data, object_pairs_hook=_pairs)
    except (ValueError, UnicodeError):
        raise JevFailure("invalid_json") from None


def _probability(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1


def validate_response(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict) or set(body) != {"model", "answers", "usage"}:
        raise JevFailure("schema_mismatch")
    model = body["model"]
    if not isinstance(model, str) or not re.fullmatch(r"jev-[a-zA-Z0-9._-]{1,80}", model):
        raise JevFailure("schema_mismatch")
    answers = body["answers"]
    if not isinstance(answers, dict) or set(answers) != set(CHOICES):
        raise JevFailure("schema_mismatch")
    for name, choices in CHOICES.items():
        answer = answers[name]
        if not isinstance(answer, dict) or set(answer) != {"type", "choice", "confidence", "probabilities"}:
            raise JevFailure("schema_mismatch")
        if answer["type"] != "choice" or not isinstance(answer["choice"], str) or answer["choice"] not in choices:
            raise JevFailure("unknown_choice")
        probabilities = answer["probabilities"]
        if (not _probability(answer["confidence"])
                or not isinstance(probabilities, dict) or set(probabilities) != set(choices)
                or not all(_probability(value) for value in probabilities.values())
                or abs(sum(probabilities.values()) - 1) > 0.02
                or probabilities[answer["choice"]] < max(probabilities.values())):
            raise JevFailure("schema_mismatch")
    usage = body["usage"]
    if (not isinstance(usage, dict) or set(usage) != {"input_tokens", "output_tokens"}
            or any(type(value) is not int or not 0 <= value <= 1_000_000 for value in usage.values())):
        raise JevFailure("schema_mismatch")
    return body


class JevClient:
    """One catalog verification and one evaluation; no retries or alternate models.

    Socket timeouts are supplemented by the owning worker's wall-clock deadline.
    Proxies are disabled to keep direct native measurements and credential scope.
    """

    def __init__(self, key: str, timeout_seconds: float, *, opener=None):
        self._key = key
        self.timings: dict[str, float] = {}
        self.timeout_seconds = timeout_seconds
        self._opener = opener
        # One worker owns one client. Reuse TLS between catalog and evaluation;
        # no process-global pool, redirects, proxies or automatic POST retries.
        self._connection = None if opener else http.client.HTTPSConnection(
            "api.typesafe.ai", timeout=timeout_seconds,
        )

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()

    def _request(self, path: str, payload: Mapping[str, Any] | None = None) -> Any:
        if not self._key:
            raise JevFailure("missing_credential")
        data = None if payload is None else json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode()
        request = urllib.request.Request(
            BASE_URL + path, data=data,
            headers={"Authorization": "Bearer " + self._key, "Content-Type": "application/json"},
            method="GET" if data is None else "POST",
        )
        try:
            if self._opener is not None:
                response = self._opener.open(request, timeout=self.timeout_seconds)
            else:
                self._connection.request(request.get_method(), path, body=data, headers=dict(request.header_items()))
                response = self._connection.getresponse()
            with response:
                if self._opener is None and response.status != 200:
                    raise JevFailure({429: "rate_limited", 401: "authentication", 403: "authentication"}.get(
                        response.status, "http_error",
                    ))
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            status = error.code
            error.close()
            raise JevFailure({429: "rate_limited", 401: "authentication", 403: "authentication"}.get(
                status, "http_error",
            )) from None
        except (TimeoutError, socket.timeout):
            raise JevFailure("timeout") from None
        except urllib.error.URLError as error:
            category = "timeout" if isinstance(error.reason, TimeoutError) else "connection"
            raise JevFailure(category) from None
        except (OSError, http.client.HTTPException):
            raise JevFailure("connection") from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise JevFailure("response_too_large")
        return decode(raw)

    def evaluate(self, state_json: str) -> dict[str, Any]:
        state = decode(state_json.encode())
        validate_state(state)
        start = time.perf_counter()
        try:
            catalog = self._request("/v1/models")
        finally:
            self.timings["catalog_latency_ms"] = (time.perf_counter() - start) * 1000
        if (not isinstance(catalog, dict) or not isinstance(catalog.get("models"), list)
                or not all(isinstance(item, dict) and isinstance(item.get("name"), str)
                           for item in catalog["models"])):
            raise JevFailure("catalog_schema")
        if MODEL not in {item["name"] for item in catalog["models"]}:
            # Never silently substitute a different live identifier.
            raise JevFailure("model_unavailable")
        start = time.perf_counter()
        self.timings["jev_request_started"] = start
        try:
            result = validate_response(self._request("/v1/systemone", {
                "state": state, "model": MODEL, "questions": QUESTIONS,
            }))
        finally:
            self.timings["jev_request_finished"] = time.perf_counter()
            self.timings["jev_latency_ms"] = (self.timings["jev_request_finished"] - start) * 1000
        # The authenticated catalog advertises aliases, while System One returns
        # a concrete semantic version (observed jev-latest -> jev-1.13.0).
        # Accept that narrow canonical form only after verifying our requested
        # alias above. Never substitute an unadvertised request model.
        if (result["model"] not in {item["name"] for item in catalog["models"]}
                and not re.fullmatch(r"jev-[0-9]+\.[0-9]+\.[0-9]+", result["model"])):
            raise JevFailure("model_unavailable")
        return {"response": result, **self.timings}
