"""Bounded session-owned Jev advice. No execution or model-selection imports.

A single-flight persistent worker amortizes interpreter, catalog and TLS setup.
All requests have a wall deadline. Shutdown kills/reaps network work, including
DNS stalls; neither provider failures nor advice change execution authority.
"""
from __future__ import annotations

from collections import Counter
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

from .decision_taxonomy import SCHEMA_VERSION, allowed_action, question, validate_request
from .jev import JevFailure, decode, validate_response
from .jev_shadow import _CAPACITY, FailureCooldown
from .provider_access import resolve_typesafe_credential


class DecisionSession:
    # Resource ceilings, not claimed optimal latency/quality thresholds. The
    # request timeout and 0.90 confidence floor retain the routing experiment's
    # existing conservative bounds. No 25 ms wait default is introduced.
    MAX_CALLS = 64
    MIN_CONFIDENCE = 0.90

    def __init__(self, *, mode="OFF", timeout_ms=1500, credential=None, popen=None):
        self.mode = mode if mode in {"OFF", "SHADOW", "COOPERATIVE"} else "OFF"
        self.timeout_ms = timeout_ms if type(timeout_ms) is int and 100 <= timeout_ms <= 3000 else 1500
        self.credential = credential or resolve_typesafe_credential
        self.popen = popen or subprocess.Popen
        self.closed = threading.Event()
        self.request_lock = threading.Lock()
        self.admission_lock = threading.Lock()
        self.worker_lock = threading.RLock()
        self.metrics_lock = threading.Lock()
        self.process = None
        self.reader = None
        self.monitor = None
        self.commands = queue.Queue(maxsize=1)
        self.responses = None
        self.capacity_owned = False
        self.retiring = False
        self.revision = -1
        self.cache = None
        self.calls = 0
        self.metrics = Counter()
        self.by_type = Counter()
        self.last_timing = {}
        self.last_jev_model = None
        self.cooldown = FailureCooldown(capacity=1)
        self.cooldown_key = Path("session")

    def _count(self, name, amount=1):
        with self.metrics_lock:
            self.metrics[name] += amount

    def snapshot(self):
        with self.metrics_lock:
            return {"schema_version": SCHEMA_VERSION,
                    "counts": dict(self.metrics), "calls_by_type": dict(self.by_type),
                    "call_count_semantics": "supervised attempts; completed_evaluations separately",
                    "last_timing": dict(self.last_timing), "jev_model": self.last_jev_model,
                    "agent_overrides": None, "model_turns_avoided": None,
                    "cost": None, "cost_source": "unavailable"}

    def _fallback(self, reason):
        return {"selected_action": None, "confidence": None, "evidence": reason,
                "fallback_required": True}

    def _start(self, deadline, abandoned):
        with self.worker_lock:
            if self.closed.is_set():
                raise JevFailure("closed")
            if self.retiring:
                raise JevFailure("worker_failure")
            if self.process is not None:
                return
        key = self.credential()
        if not key:
            raise JevFailure("missing_credential")
        with self.worker_lock:
            if self.closed.is_set():
                raise JevFailure("closed")
            if abandoned.is_set() or time.perf_counter() >= deadline:
                raise JevFailure("timeout")
            if not _CAPACITY.acquire(blocking=False):
                raise JevFailure("capacity")
            self.capacity_owned = True
            try:
                env = {name: os.environ[name] for name in ("SYSTEMROOT", "WINDIR") if name in os.environ}
                self.process = self.popen(
                    [sys.executable, str(Path(__file__).with_name("jev_worker.py")), "--session"],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    env=env, cwd=str(Path(__file__).parent),
                )
                process = self.process
                responses = self.responses = queue.Queue(maxsize=1)

                def read_response():
                    try:
                        while True:
                            line = process.stdout.readline(32769)
                            if not line or len(line) > 32768:
                                break
                            responses.put_nowait(line)
                    except (OSError, ValueError, queue.Full):
                        pass
                    finally:
                        try:
                            responses.put_nowait(None)
                        except queue.Full:
                            pass

                self.reader = threading.Thread(target=read_response, name="jev-session-reader", daemon=True)
                self.reader.start()
                process.stdin.write(json.dumps({"key": key, "timeout_seconds": self.timeout_ms / 1000}).encode() + b"\n")
                process.stdin.flush()
                self._count("worker_starts")
            except Exception:
                self._stop_worker()
                raise JevFailure("worker_failure") from None

    def _stop_worker(self, *, wait_timeout=2):
        with self.worker_lock:
            self.retiring = True
            process, reader = self.process, self.reader
            try:
                if process is not None:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=wait_timeout)
            finally:
                # Never drop an unreaped process. A failed wait retains ownership
                # for close() to retry; a dead process releases capacity even if
                # a reader or stream raises during cleanup.
                if process is None or process.poll() is not None:
                    try:
                        if reader is not None:
                            reader.join(timeout=2)
                        if process is not None:
                            for stream in (process.stdin, process.stdout):
                                if stream is not None:
                                    try:
                                        stream.close()
                                    except (OSError, ValueError):
                                        self._count("cleanup_errors")
                    finally:
                        self.process = self.reader = None
                        self.retiring = False
                        if self.capacity_owned:
                            self.capacity_owned = False
                            _CAPACITY.release()

    def close(self):
        with self.admission_lock:
            self.closed.set()
            try:
                self.commands.put_nowait(None)
            except queue.Full:
                pass  # A queued request observes closed and the monitor then exits.
        # Kill/reap/stream operations belong only to the monitor. Never wait
        # for its worker_lock on the calling/UI thread.
        monitor = self.monitor
        if monitor is not None and monitor is not threading.current_thread():
            monitor.join(timeout=5)
        # Late completions check closed before publication. Do not acquire the
        # single-flight lock here: cancellation must interrupt an active call.

    def _monitor_loop(self):
        # Linux parent-death signals belong to the creating OS thread. Keep
        # this owner alive across calls, not merely the Python process, or each
        # completed request would kill the supposedly persistent worker.
        try:
            while True:
                work = self.commands.get()
                if work is None:
                    return
                request, cacheable, started, abandoned, done, completed = work
                try:
                    completed.append(self._decide(request, cacheable=cacheable,
                                                  started=started, abandoned=abandoned))
                except Exception:
                    completed.append(self._fallback("worker_failure"))
                finally:
                    if self.retiring:
                        done.set()
                        self._retire_worker()
                    self.request_lock.release()
                    done.set()
                if self.closed.is_set():
                    return
        finally:
            self._retire_worker()

    def _retire_worker(self):
        # Monitor-owned bounded polling retains capacity until observed death.
        # Even an OS wait ignoring its timeout cannot block the calling thread.
        while True:
            try:
                self._stop_worker(wait_timeout=0.1)
            except (OSError, subprocess.SubprocessError):
                self._count("cleanup_errors")
                time.sleep(0.05)
            if not self.retiring:
                return

    def decide(self, request, *, cacheable=False):
        started = time.perf_counter()
        self._count("requests")
        if self.closed.is_set() or self.mode != "COOPERATIVE":
            self._count("skipped")
            result = self._fallback("closed" if self.closed.is_set() else "disabled")
        elif not self.request_lock.acquire(blocking=False):
            self._count("skipped")
            result = self._fallback("busy")
        else:
            done, abandoned = threading.Event(), threading.Event()
            completed = []
            # The caller's deadline covers credential lookup, startup, I/O and
            # slow reaping. Cleanup remains owned by this single joined monitor;
            # new decisions fail open while it is retiring work. No late result
            # can be published as an accepted decision.
            try:
                with self.admission_lock:
                    if self.closed.is_set():
                        raise JevFailure("closed")
                    if self.monitor is None:
                        self.monitor = threading.Thread(target=self._monitor_loop, name="jev-session-monitor", daemon=True)
                        self.monitor.start()
                    self.commands.put_nowait((request, cacheable, started, abandoned, done, completed))
            except Exception:
                self.request_lock.release()
                result = self._fallback("worker_failure")
            else:
                deadline = started + self.timeout_ms / 1000
                while not self.closed.is_set() and time.perf_counter() < deadline:
                    if done.wait(min(0.05, max(0, deadline - time.perf_counter()))):
                        break
                if completed and not self.closed.is_set() and time.perf_counter() <= deadline:
                    result = completed[0]
                else:
                    abandoned.set()
                    self.cache = None
                    result = self._fallback("cancelled" if self.closed.is_set() else "timeout")
        elapsed = (time.perf_counter() - started) * 1000
        result.setdefault("timing", {"rtt_ms": None, "useful_overlap_ms": 0.0})["blocking_ms"] = elapsed
        self._count("blocking_ms", elapsed)
        if result["fallback_required"]:
            self._count("fallbacks")
            self._count("fallback_" + result["evidence"])
            if result["evidence"] == "timeout":
                self._count("deadline_misses")
        else:
            self._count("accepted")
        return result

    def _decide(self, request, *, cacheable, started, abandoned):
        result = None
        try:
            if self.closed.is_set() or self.mode != "COOPERATIVE":
                self._count("skipped")
                result = self._fallback("closed" if self.closed.is_set() else "disabled")
                return result
            try:
                request = validate_request(request)
                encoded = json.dumps(request, sort_keys=True, separators=(",", ":"), allow_nan=False)
                request = json.loads(encoded)  # Caller mutation cannot change in-flight evidence.
            except (JevFailure, TypeError, ValueError) as error:
                self._count("skipped")
                result = self._fallback(error.category if isinstance(error, JevFailure) else "invalid_state")
                return result
            revision = request["execution_state"]["revision"]
            if revision < self.revision:
                result = self._fallback("stale")
                return result
            if revision != self.revision:
                self.cache = None
                self.revision = revision
            if cacheable and self.cache is not None and self.cache[0] == encoded:
                self._count("cache_hits")
                result = dict(self.cache[1])
                return result
            # A different request at the same revision cannot reuse old advice.
            self.cache = None
            if self.cooldown.suppressed(self.cooldown_key):
                self._count("skipped")
                result = self._fallback("circuit_open")
                return result
            if self.calls >= self.MAX_CALLS:
                self._count("skipped")
                result = self._fallback("budget")
                return result
            self.calls += 1
            with self.metrics_lock:
                self.by_type[request["decision_type"]] += 1
            self._count("calls")
            try:
                deadline = started + self.timeout_ms / 1000
                self._start(deadline, abandoned)
                with self.worker_lock:
                    if self.closed.is_set() or self.process is None:
                        raise JevFailure("closed")
                    if abandoned.is_set() or time.perf_counter() >= deadline:
                        raise JevFailure("timeout")
                    self.process.stdin.write(encoded.encode() + b"\n")
                    self.process.stdin.flush()
                    responses = self.responses
                while True:
                    if self.closed.is_set():
                        raise JevFailure("cancelled")
                    remaining = deadline - time.perf_counter()
                    if remaining <= 0:
                        raise queue.Empty
                    try:
                        raw = responses.get(timeout=min(0.05, remaining))
                        break
                    except queue.Empty:
                        continue
                if raw is None:
                    raise JevFailure("worker_failure")
                value = decode(raw)
                if not isinstance(value, dict):
                    raise JevFailure("worker_failure")
                if value.get("failure_category"):
                    from .jev_shadow import FAILURES
                    category = value["failure_category"]
                    raise JevFailure(category if category in FAILURES else "worker_failure")
                response = validate_response(value.get("response"), {"decision": question(request)["decision"]["criteria"]})
                if self.closed.is_set() or abandoned.is_set() or (time.perf_counter() - started) * 1000 >= self.timeout_ms:
                    raise JevFailure("closed" if self.closed.is_set() else "timeout")
                self.cooldown.observe(self.cooldown_key, None)
                self._count("completed_evaluations")
                answer = response["answers"]["decision"]
                action = answer["choice"]
                self._count("input_tokens", response["usage"]["input_tokens"])
                self._count("output_tokens", response["usage"]["output_tokens"])
                timing = {name: value.get(name) for name in ("jev_latency_ms", "catalog_latency_ms")}
                with self.metrics_lock:
                    self.last_timing = timing
                    self.last_jev_model = response["model"]
                if not allowed_action(request, action):
                    result = self._fallback("hard_policy")
                elif answer["confidence"] < self.MIN_CONFIDENCE or action == "agent":
                    result = self._fallback("uncertain")
                else:
                    result = {"selected_action": action, "confidence": answer["confidence"],
                              "evidence": "native_choice_probabilities", "fallback_required": False,
                              "probabilities": answer["probabilities"]}
                    self.cache = (encoded, dict(result)) if cacheable else None
                result["confidence"] = answer["confidence"]
                result["probabilities"] = answer["probabilities"]
                result["timing"] = {"rtt_ms": timing["jev_latency_ms"],
                                    "catalog_ms": timing["catalog_latency_ms"], "useful_overlap_ms": 0.0}
                return result
            except queue.Empty:
                result = self._fallback("timeout")
            except JevFailure as error:
                self._count("errors")
                result = self._fallback(error.category)
            except Exception:
                self._count("errors")
                result = self._fallback("worker_failure")
            self.cooldown.observe(self.cooldown_key, result["evidence"])
            try:
                self._stop_worker()
            except (OSError, subprocess.SubprocessError):
                self._count("cleanup_errors")
            return result
        finally:
            if abandoned.is_set():
                self.cache = None
                self._count("late_results_discarded")
