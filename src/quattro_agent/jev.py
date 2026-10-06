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

SCHEMA_VERSION = "quattro-jev-decisions-v2"
MODEL = "jev-latest"
BASE_URL = "https://api.typesafe.ai"
MAX_RESPONSE_BYTES = 32_768
MAX_REQUEST_BODY_BYTES = 16_384


class JevFailure(Exception):
    """Only a fixed category, never provider bodies, URLs, or credentials."""

    def __init__(self, category: str):
        super().__init__(category)
        self.category = category


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise JevFailure("invalid_json")
        result[name] = value
    return result


def decode(data: bytes) -> Any:
    def reject_constant(_value: str) -> None:
        raise JevFailure("invalid_json")
    try:
        return json.loads(data, object_pairs_hook=_pairs, parse_constant=reject_constant)
    except (ValueError, UnicodeError, RecursionError, OverflowError):
        raise JevFailure("invalid_json") from None


def _probability(value: Any) -> bool:
    return type(value) in (int, float) and 0 <= value <= 1 and math.isfinite(value)


def validate_response(body: Any, choices: Mapping[str, Any]) -> dict[str, Any]:
    if (not isinstance(choices, Mapping) or not choices
            or any(not isinstance(vocabulary, Mapping) or not 2 <= len(vocabulary) <= 8
                   for vocabulary in choices.values())):
        raise JevFailure("schema_mismatch")
    if not isinstance(body, dict) or set(body) != {"model", "answers", "usage"}:
        raise JevFailure("schema_mismatch")
    model = body["model"]
    if not isinstance(model, str) or not re.fullmatch(r"jev-[a-zA-Z0-9._-]{1,80}", model):
        raise JevFailure("schema_mismatch")
    answers = body["answers"]
    if not isinstance(answers, dict) or set(answers) != set(choices):
        raise JevFailure("schema_mismatch")
    for name, vocabulary in choices.items():
        answer = answers[name]
        if not isinstance(answer, dict) or set(answer) != {"type", "choice", "confidence", "probabilities"}:
            raise JevFailure("schema_mismatch")
        if answer["type"] != "choice" or not isinstance(answer["choice"], str) or answer["choice"] not in vocabulary:
            raise JevFailure("unknown_choice")
        probabilities = answer["probabilities"]
        if (not _probability(answer["confidence"])
                or not isinstance(probabilities, dict) or set(probabilities) != set(vocabulary)
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
    """One evaluation with optional catalog verification; no retries or alternate models.

    Socket timeouts are supplemented by the owning worker's wall-clock deadline.
    Proxies are disabled to keep direct native measurements and credential scope.
    """

    def __init__(self, key: str, timeout_seconds: float, *, opener=None):
        self._key = key
        self.timings: dict[str, float] = {}
        self.timeout_seconds = timeout_seconds
        self._opener = opener
        self._catalog = None
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
        if data is not None:
            if len(data) > MAX_REQUEST_BODY_BYTES:
                raise JevFailure("invalid_state")
            self.timings["request_body_bytes"] = len(data)
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

    def evaluate(self, request: Mapping[str, Any], *, reuse_catalog: bool = False,
                 verify_catalog: bool = True) -> dict[str, Any]:
        """Evaluate only an authored dynamic envelope; legacy routing is rejected."""
        if __package__:
            from .decision_taxonomy import question, validate_dynamic_request
        else:
            from decision_taxonomy import question, validate_dynamic_request
        validated = validate_dynamic_request(request)
        return self.evaluate_questions(validated, question(validated), reuse_catalog=reuse_catalog,
                                       verify_catalog=verify_catalog)

    def evaluate_dynamic(self, request: Mapping[str, Any], *, reuse_catalog: bool = False,
                         verify_catalog: bool = True) -> dict[str, Any]:
        return self.evaluate(request, reuse_catalog=reuse_catalog, verify_catalog=verify_catalog)

    def evaluate_questions(self, state: Mapping[str, Any], questions: Mapping[str, Any],
                           *, reuse_catalog: bool = False, verify_catalog: bool = True) -> dict[str, Any]:
        """Use the authored native Choice contract with no raw-state bypass."""
        if __package__:
            from .decision_taxonomy import question, validate_dynamic_request
        else:
            from decision_taxonomy import question, validate_dynamic_request
        validated = validate_dynamic_request(state)
        state = decode(json.dumps(validated, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())
        expected_questions = question(state)
        if questions != expected_questions:
            raise JevFailure("invalid_state")
        questions = expected_questions
        catalog = None
        if verify_catalog:
            start = time.perf_counter()
            try:
                catalog = self._catalog if reuse_catalog and self._catalog is not None else self._request("/v1/models")
            finally:
                self.timings["catalog_latency_ms"] = (time.perf_counter() - start) * 1000
            if (not isinstance(catalog, dict) or not isinstance(catalog.get("models"), list)
                    or not all(isinstance(item, dict) and isinstance(item.get("name"), str)
                               for item in catalog["models"])):
                raise JevFailure("catalog_schema")
            if MODEL not in {item["name"] for item in catalog["models"]}:
                # Never silently substitute a different live identifier.
                raise JevFailure("model_unavailable")
            self._catalog = catalog
        else:
            # The fixed runtime alias is sent directly. A missing alias fails at
            # POST; the returned model still must be its narrow canonical form.
            self.timings["catalog_latency_ms"] = 0.0
        start = time.perf_counter()
        self.timings["jev_request_started"] = start
        try:
            result = validate_response(self._request("/v1/systemone", {
                "state": state, "model": MODEL, "questions": questions,
            }), {name: question["criteria"] for name, question in questions.items()})
        finally:
            self.timings["jev_request_finished"] = time.perf_counter()
            self.timings["jev_latency_ms"] = (self.timings["jev_request_finished"] - start) * 1000
        # The authenticated catalog advertises aliases, while System One returns
        # a concrete semantic version (observed jev-latest -> jev-1.13.0).
        # The fixed runtime alias may skip catalog I/O, but still accepts only
        # the narrow canonical form. Never substitute an unexpected model.
        if ((catalog is None or result["model"] not in {item["name"] for item in catalog["models"]})
                and not re.fullmatch(r"jev-[0-9]+\.[0-9]+\.[0-9]+", result["model"])):
            raise JevFailure("model_unavailable")
        return {"response": result, **self.timings}
