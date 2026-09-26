"""Per-turn authority shared by native frontend adapters.

No prompt, response, fingerprint, or exception text is written to telemetry.
The frontend is presentation metadata, never a delegation signal.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import http.client
import json
import os
from pathlib import Path
import re
import socket
import threading
import time
from urllib.parse import urlencode, urlsplit

from .jev_shadow import lifecycle as jev_lifecycle, annotate as annotate_signals, take_scope, current_evidence
from .turn_routing import route_turn, active_account_health, CREDENTIAL_RESPONSE
from .model_registry import (
    ExecutionPlan, default_policy_path, load_model_registry, target_matches_actual,
)
from .omniroute import APPROVED_BASE_URL, validate_omniroute_runtime_capabilities
from .paths import model_catalog_path
from .privacy import redact_secret_text


_SECRET = re.compile(r"(?i)\b(password|passwd|api[ _-]?key|access[ _-]?token|secret|credential)\b")
BUDGETS = {"FAST": 20.0, "STANDARD": 60.0, "REASONING": 90.0}
MAX_BODY = 4_000_000


@dataclass
class Turn:
    session_id: str
    thread_id: str
    turn_id: str
    frontend: str
    prompt: str = field(repr=False)
    decision: str
    plan: ExecutionPlan
    reason: str
    sensitive: bool
    started: float
    routing_ms: float
    budget: float | None
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    connection: http.client.HTTPConnection | None = field(default=None, repr=False)
    first_token_ms: float | None = None
    dispatch_ms: float | None = None
    finished: bool = False
    task_id: str | None = None
    socket: socket.socket | None = field(default=None, repr=False)
    timer: threading.Timer | None = field(default=None, repr=False)
    request_id: str | None = None
    failure_code: str | None = None
    model_requests: int = 0
    shadow_runs: tuple = field(default=(), repr=False)
    routing_evidence: dict = field(default_factory=dict, repr=False)


class TurnGate:
    """One session, fresh immutable plan for each independently classified turn."""

    def __init__(self, *, session_id: str, config: dict, directory: Path,
                 telemetry_path: Path, account: str, registry=None, delegate=None):
        self.session_id = session_id
        self.config = config
        self.directory = directory
        self.account = account
        self.registry = tuple(registry) if registry is not None else load_model_registry(
            default_policy_path(), model_catalog_path(),
        )
        self.telemetry_path = telemetry_path
        self.delegate = delegate
        self._lock = threading.RLock()
        self._active: dict[str, Turn] = {}
        self._history: dict[str, list[dict]] = {}

    @jev_lifecycle
    def begin(self, thread_id: str, prompt: str, frontend: str, params=None) -> Turn:
        started = time.monotonic()
        if frontend not in {"codex", "pi"} or not isinstance(prompt, str):
            raise ValueError("unsupported turn input")
        if not prompt.strip() or len(prompt) > 64_000 or '\x00' in prompt:
            raise ValueError("turn input exceeds supported bounds")
        with self._lock:
            if thread_id in self._active:
                raise ValueError("a turn is already active; cancel or wait before submitting")
            routed = route_turn(
                request=prompt, config=self.config, registry=self.registry, account=self.account,
                database=self.telemetry_path.parent / 'intelligence' / 'intelligence.sqlite3',
                selected_model=(params or {}).get('model'), agent='codex',
                workflow='interactive-turn', policy_name='audit-read-only',
                unavailable_routes=frozenset(active_account_health(
                    self.telemetry_path.parent / 'routing' / 'account-health.json',
                )),
            )
            decision, plan = routed.decision, routed.plan
            if redact_secret_text(prompt)[1] and decision.decision == 'DELEGATE':
                raise ValueError('remove credential values before starting persistent execution')
            sensitive = routed.features.sensitive
            ident, target, tier = plan.plan_id, plan.target, plan.target.tier
            turn = Turn(self.session_id, thread_id, ident, frontend, prompt, decision.decision,
                        plan, decision.reason, sensitive, started,
                        (time.monotonic() - started) * 1000,
                        BUDGETS[tier] if decision.decision == "DIRECT" else None)
            annotate_signals(
                turn_id=ident, plan_id=ident,
                final_decision={"execution": decision.decision,
                                "worker": None if decision.decision == 'DIRECT' else 'codex',
                                "provider": target.provider, "account": target.account,
                                "model": target.model, "reasoning_effort": plan.reasoning_effort},
                outcome_source='interactive-turns.jsonl',
            )
            turn.routing_evidence = current_evidence()
            turn.request_id = (params or {}).get('request_id')
            self._active[thread_id] = turn
            self._record(turn, "planned", False, False)
            if turn.budget:
                turn.timer = threading.Timer(max(0, turn.budget - (time.monotonic() - started)),
                                             self.cancel, args=(turn,))
                turn.timer.daemon = True
                turn.timer.start()
            turn.shadow_runs = take_scope()
            return turn

    def remaining(self, turn: Turn) -> float:
        if turn.cancel_event.is_set():
            raise TimeoutError("turn cancelled")
        remaining = (turn.started + turn.budget - time.monotonic()) if turn.budget else 180.0
        if remaining <= 0:
            raise TimeoutError("direct turn budget exhausted")
        return remaining

    @staticmethod
    def envelope(plan: ExecutionPlan) -> dict:
        return {"schema_version": 1, "requirements": {"capabilities": [],
                "minimum_context": plan.context.budget_tokens},
                "preferred_candidates": [f"{plan.target.provider}/{plan.target.model}"],
                "preference_mode": "passthrough", "task_profile_id": plan.plan_id,
                "plan_id": plan.plan_id, "routing_locked": True,
                "target": plan.target.to_dict(), "tier": plan.target.tier,
                "routing_policy_version": "quattro-authoritative-v1"}

    def locked_body(self, turn: Turn, body: dict) -> dict:
        self.remaining(turn)
        return dict(body, model=turn.plan.target.route,
                    reasoning={"effort": turn.plan.reasoning_effort},
                    routing=self.envelope(turn.plan))

    def by_plan(self, plan_id: str) -> Turn:
        with self._lock:
            for turn in self._active.values():
                if turn.plan.plan_id == plan_id and not turn.finished:
                    self.remaining(turn)
                    return turn
        raise ValueError("unknown or expired execution plan")

    def remember(self, thread_id: str, prompt: str, answer: str):
        """Share bounded native conversation context without gathering files."""
        if any(not isinstance(text, str) or _SECRET.search(text) or redact_secret_text(text)[1]
               for text in (prompt, answer)):
            return
        with self._lock:
            history = self._history.setdefault(thread_id, [])
            history.extend([{'role': 'user', 'content': prompt[-16000:]},
                            {'role': 'assistant', 'content': answer[-16000:]}])
            self._history[thread_id] = history[-12:]

    def hydrate(self, thread_id: str, turns):
        """Consume history already requested by the native UI, never scan a repo."""
        if not isinstance(turns, list):
            return
        with self._lock:
            self._history[thread_id] = []
        for turn in sorted(turns, key=lambda row: row.get('startedAt') or 0)[-6:]:
            prompt, answer = '', ''
            for item in turn.get('items', []):
                if item.get('type') == 'userMessage':
                    prompt = '\n'.join(p.get('text', '') for p in item.get('content', [])
                                       if p.get('type') == 'text')
                elif item.get('type') == 'agentMessage':
                    answer += item.get('text', '')
            if prompt and answer:
                self.remember(thread_id, prompt, answer)

    def import_history(self, thread_id: str, messages):
        if not isinstance(messages, list) or len(messages) > 12:
            return
        safe = []
        total = 0
        for item in messages:
            if not isinstance(item, dict) or item.get('role') not in {'user', 'assistant'}:
                return
            text = item.get('content')
            if not isinstance(text, str) or _SECRET.search(text) or redact_secret_text(text)[1]:
                return
            total += len(text)
            if total > 32000:
                return
            safe.append({'role': item['role'], 'content': text})
        if safe:
            with self._lock:
                self._history[thread_id] = safe

    def conversation_context(self, turn: Turn) -> str:
        with self._lock:
            history = list(self._history.get(turn.thread_id, []))
        bound = min(32000, turn.plan.context.conversation_budget_tokens * 4)
        while history and len(json.dumps(history)) > bound:
            history.pop(0)
        return json.dumps(history) if history else ''

    def cancel_all(self):
        with self._lock:
            turns = list(self._active.values())
        for turn in turns:
            self.cancel(turn)

    def _request(self, turn: Turn, method: str, path: str, body=None):
        base = urlsplit(APPROVED_BASE_URL)
        cls = http.client.HTTPSConnection if base.scheme == 'https' else http.client.HTTPConnection
        conn = cls(base.hostname, base.port, timeout=min(3.0, self.remaining(turn)))
        turn.connection = conn
        if method == 'POST':
            turn.model_requests += 1
            if turn.dispatch_ms is None:
                turn.dispatch_ms = (time.monotonic() - turn.started) * 1000 - turn.routing_ms
        data = json.dumps(body).encode() if body is not None else None
        conn.request(method, base.path.rstrip('/') + path, data,
                     {"Content-Type": "application/json"})
        turn.socket = conn.sock
        if conn.sock:
            conn.sock.settimeout(self.remaining(turn))
        response = conn.getresponse()
        if response.status != 200:
            turn.failure_code = f'provider_http_{response.status}'
            conn.close()
            raise RuntimeError(f"locked transport failed (HTTP {response.status})")
        return conn, response

    def direct(self, turn: Turn) -> str:
        if turn.decision != 'DIRECT':
            raise ValueError("direct transport requires a DIRECT plan")
        if turn.sensitive:
            # No filesystem search and no credential request forwarded to a model.
            return CREDENTIAL_RESPONSE
        validate_omniroute_runtime_capabilities(
            APPROVED_BASE_URL, timeout_seconds=min(3.0, self.remaining(turn)),
        )
        with self._lock:
            history = list(self._history.get(turn.thread_id, []))
        max_chars = turn.plan.context.conversation_budget_tokens * 4
        selected = []
        used = len(turn.prompt)
        for item in reversed(history):
            size = len(item['content'])
            if used + size > max_chars:
                break
            used += size
            selected.insert(0, item)
        body = self.locked_body(turn, {
            "input": selected + [{"role": "user", "content": turn.prompt}],
            "stream": True, "tools": [], "max_output_tokens": 1500,
            "instructions": "Answer the user's question directly and concisely. No tools are available.",
        })
        dispatched = time.monotonic()
        turn.dispatch_ms = (dispatched - turn.started) * 1000 - turn.routing_ms
        conn, response = self._request(turn, 'POST', '/responses', body)
        text = []
        total = 0
        completed = False
        try:
            while True:
                if conn.sock:
                    conn.sock.settimeout(self.remaining(turn))
                raw = response.readline(MAX_BODY + 1)
                self.remaining(turn)
                if not raw:
                    break
                total += len(raw)
                if total > MAX_BODY:
                    raise RuntimeError("response exceeds bounded output size")
                if not raw.startswith(b'data:'):
                    continue
                value = raw[5:].strip()
                if value == b'[DONE]':
                    break
                event = json.loads(value)
                kind = event.get('type')
                if kind == 'response.output_text.delta':
                    if turn.first_token_ms is None:
                        turn.first_token_ms = (time.monotonic() - dispatched) * 1000
                    text.append(str(event.get('delta', '')))
                elif kind == 'response.completed':
                    completed = True
                    if not text:
                        result = event.get('response', {})
                        for item in result.get('output', []):
                            for part in item.get('content', []):
                                if part.get('type') == 'output_text':
                                    text.append(part.get('text', ''))
                    break
                elif kind in {'error', 'response.failed', 'response.incomplete'}:
                    raise RuntimeError("provider did not complete the direct response")
        finally:
            conn.close()
            turn.connection = None
        if not completed or not ''.join(text).strip():
            raise RuntimeError("direct response did not complete")
        self.verify_receipt(turn)
        answer = ''.join(text)
        if redact_secret_text(answer)[1]:
            turn.sensitive = True
        # Only non-sensitive context; credential-shaped responses never enter history.
        if not turn.sensitive and not _SECRET.search(answer):
            with self._lock:
                history.extend([{"role": "user", "content": turn.prompt},
                                {"role": "assistant", "content": answer}])
                self._history[turn.thread_id] = history[-12:]
        return answer

    def verify_receipt(self, turn: Turn):
        receipt = None
        for attempt in range(4):
            self.remaining(turn)
            conn, response = self._request(turn, 'GET', '/routing/locked-receipts?' +
                                           urlencode({'plan_id': turn.plan.plan_id}))
            try:
                raw = response.read(128_001)
                self.remaining(turn)
                candidate = json.loads(raw) if len(raw) <= 128_000 else None
            except (ValueError, UnicodeError):
                candidate = None
            finally:
                conn.close()
                turn.connection = None
            if not isinstance(candidate, dict):
                break
            receipt = candidate
            if candidate.get('plan_id') != turn.plan.plan_id:
                break
            if 'success' in candidate or candidate.get('status') != 'pending':
                break
            if attempt < 3:
                turn.cancel_event.wait(min(0.05 * (attempt + 1), self.remaining(turn)))
        if (not isinstance(receipt, dict)
                or receipt.get('plan_id') != turn.plan.plan_id or receipt.get('success') is not True
                or not target_matches_actual(turn.plan.target,
                    actual_provider=receipt.get('actual_provider'),
                    actual_account=receipt.get('actual_account'),
                    actual_model=receipt.get('actual_model'),
                    actual_route=receipt.get('actual_route'))):
            turn.failure_code = 'locked_receipt_mismatch'
            raise RuntimeError("locked execution receipt failed verification")

    @staticmethod
    def _close_signals(turn: Turn):
        for run in getattr(turn, 'shadow_runs', ()):
            try:
                run.finish_owned()
            except Exception:
                pass  # Optional evidence must not interrupt turn cleanup.

    def cancel(self, turn: Turn):
        turn.failure_code = ('budget_exceeded' if turn.budget and
                             time.monotonic() - turn.started >= turn.budget else 'cancelled')
        turn.cancel_event.set()
        if turn.socket:
            try:
                turn.socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        connection = turn.connection
        if connection:
            connection.close()
        TurnGate._close_signals(turn)

    def cancel_thread(self, thread_id: str, request_id: str | None = None):
        with self._lock:
            turn = self._active.get(thread_id)
        if turn and (request_id is None or turn.request_id == request_id):
            self.cancel(turn)

    def finish(self, turn: Turn, status='completed', tools_used=False, agent_lifecycle=False):
        with self._lock:
            if turn.finished:
                return
            turn.finished = True
            TurnGate._close_signals(turn)
            if turn.timer:
                turn.timer.cancel()
            if turn.connection:
                turn.connection.close()
                turn.connection = None
            self._record(turn, status, tools_used, agent_lifecycle)
            if self._active.get(turn.thread_id) is turn:
                del self._active[turn.thread_id]
            turn.prompt = ''

    def _record(self, turn: Turn, status: str, tools: bool, lifecycle: bool):
        # Allowlisted metadata only. Never serialize params, exceptions, or content.
        if status not in {'planned', 'completed', 'failed', 'interrupted'}:
            status = 'failed'
        event = {"schema_version": 1, "session_id": self.session_id,
                 "timestamp": datetime.now(timezone.utc).isoformat(),
                 "turn_id": turn.turn_id, "frontend": turn.frontend, "task_id": turn.task_id,
                 "decision": turn.decision, "profile": turn.plan.target.tier,
                 "provider": turn.plan.target.provider, "account": turn.plan.target.account,
                 "model": turn.plan.target.model, "effort": turn.plan.reasoning_effort,
                 "plan_id": turn.plan.plan_id, "reason_code": turn.reason,
                 "tools_used": bool(tools), "agent_lifecycle": bool(lifecycle),
                 "routing_ms": round(turn.routing_ms, 3), "dispatch_ms": turn.dispatch_ms,
                 "first_token_ms": turn.first_token_ms,
                 "duration_ms": round((time.monotonic() - turn.started) * 1000, 3),
                 "budget_seconds": turn.budget, "status": status,
                 "failure_code": turn.failure_code if status != 'completed' else None,
                 "model_requests": turn.model_requests,
                 "fallback_events": [], "evidence_provenance": "quattro_per_turn_gate",
                 "routing": dict(turn.routing_evidence)}
        for run in turn.shadow_runs:
            if run.done.is_set():
                event['routing']['jev'] = {name: run.record.get(name) for name in (
                    'answers', 'jev_model', 'jev_latency_ms', 'input_usage', 'output_usage',
                    'cost', 'cost_source', 'failure_category', 'status',
                )}
        self.telemetry_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        fd = os.open(self.telemetry_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'a') as stream:
            stream.write(json.dumps(event, separators=(',', ':')) + '\n')
