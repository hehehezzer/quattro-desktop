"""Controlled probe-gold contracts for autonomous routing evaluation."""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Callable
from typing import Any

from .features import decision_profile
from .store import IntelligenceStore
from .telemetry import request_fingerprint, sanitize_request


DIRECT_CATEGORIES = (
    "explanation",
    "comparison",
    "reasoning",
    "summarization",
    "drafting",
    "conceptual_analysis",
)
DELEGATE_CATEGORIES = (
    "repository_inspection",
    "file_lookup",
    "implementation",
    "test_build_execution",
    "tool_investigation",
    "external_research",
    "multi_source_verification",
    "multi_step_execution",
    "system_investigation",
    "noncoding_execution",
)

_DIRECT_TOPICS = {
    "train": (
        "write-ahead logging", "capability-based security", "event sourcing",
        "optimistic concurrency", "semantic versioning", "dependency injection",
        "cache invalidation", "rate limiting", "idempotency", "structured logging",
        "eventual consistency", "feature flags", "backpressure", "data normalization",
        "least privilege", "retry budgets", "immutable data", "queue fairness",
        "schema evolution", "graceful degradation", "content-addressed storage",
        "cooperative cancellation", "boundary validation", "observability",
        "reproducible builds", "memory locality", "accessibility semantics",
        "failure domains", "transaction isolation", "API pagination",
    ),
    "validation": (
        "vector clocks", "zero-copy parsing", "circuit breakers", "token buckets",
        "database snapshots", "branch prediction", "tail latency", "clock skew",
        "distributed leases", "Merkle trees", "read-copy-update", "CQRS",
        "Bloom filters", "saga compensation", "dead-letter queues", "Paxos",
        "Raft elections", "content negotiation", "canonical serialization",
        "monotonic clocks", "responsive typography", "color contrast",
        "progressive disclosure", "keyboard focus", "data provenance",
        "causal consistency", "load shedding", "bulkheads", "hedged requests",
        "priority inversion",
    ),
    "test": (
        "consistent hashing", "snapshot isolation", "write amplification",
        "garbage collection", "copy-on-write", "actor supervision", "CRDTs",
        "two-phase commit", "conflict-free replication", "online migrations",
        "privacy budgets", "differential privacy", "capability tokens",
        "proof-carrying data", "stable sorting", "amortized analysis",
        "property-based testing", "metamorphic testing", "contract testing",
        "fault injection", "human factors", "information scent", "error affordances",
        "local-first software", "offline synchronization", "temporal coupling",
        "referential transparency", "memoization", "lock-free progress",
        "deterministic replay",
    ),
}

_DIRECT_TEMPLATES: dict[str, tuple[str, ...]] = {
    "train": (
        "Explain {topic} to a technical reader without using tools or external sources.",
        "Compare {topic} with the closest alternative using only general knowledge.",
        "Reason through the main trade-offs of {topic}; no browsing or execution is needed.",
        "Summarize this supplied concept in five sentences: {topic} improves system design when applied deliberately.",
        "Draft a short neutral introduction to {topic} from the information in this request.",
        "Analyze the concept of {topic} and identify two common misconceptions without inspecting any repository.",
    ),
    "validation": (
        "Give a self-contained explanation of {topic}; do not browse, inspect files, or run anything.",
        "Contrast {topic} against a simpler approach and state when each is appropriate.",
        "Work out the conceptual advantages and limitations of {topic} from first principles.",
        "Condense the following supplied note: {topic} is useful, but its operational costs must be explicit.",
        "Write a concise paragraph introducing {topic} for an internal handbook; no research is required.",
        "Evaluate the idea of {topic} conceptually, without verifying any external or runtime state.",
    ),
    "test": (
        "Teach me the core intuition behind {topic} using a small hypothetical example only.",
        "Describe how {topic} differs from a conventional alternative; answer directly from established concepts.",
        "Derive the likely trade-offs of {topic} without consulting current information or tools.",
        "Provide the key points from this supplied sentence: {topic} trades simplicity for stronger guarantees.",
        "Compose a brief, plain-language overview of {topic} without adding researched facts.",
        "Assess the conceptual role of {topic}; repository access and execution are explicitly out of scope.",
    ),
}

_DIRECT_LENSES = (
    "failure recovery", "operator ergonomics", "data integrity", "resource bounds",
    "security boundaries", "maintenance cost", "latency behavior", "auditability",
    "backward compatibility", "user comprehension", "deployment risk", "testability",
    "capacity planning", "error isolation", "privacy impact", "portability",
    "debuggability", "change management", "access control", "service ownership",
    "schema safety", "rollback design", "observability signals", "team coordination",
    "performance limits", "interface clarity", "state transitions", "failure messaging",
    "dependency risk", "operational simplicity",
)

_DELEGATE_SUBJECTS = {
    "train": (
        "authentication middleware", "billing webhook", "background scheduler",
        "configuration loader", "migration runner", "session cache",
    ),
    "validation": ("audit logger", "rate-limit gateway", "artifact packager"),
    "test": ("notification worker", "feature registry", "backup verifier"),
}

_DELEGATE_DETAILS = {
    "authentication middleware": "credential propagation and permission checks",
    "billing webhook": "idempotent invoice settlement and replay handling",
    "background scheduler": "lease expiry and missed-job recovery",
    "configuration loader": "precedence rules and invalid-value fallback",
    "migration runner": "transaction boundaries and partial rollback",
    "session cache": "revocation propagation and stale-entry eviction",
    "audit logger": "tamper evidence and bounded retention",
    "rate-limit gateway": "burst accounting and tenant isolation",
    "artifact packager": "content integrity and reproducible archives",
    "notification worker": "delivery deduplication and retry exhaustion",
    "feature registry": "rollout targeting and default-state safety",
    "backup verifier": "restore sampling and checksum provenance",
}
_SCENARIO_CONTEXT = {
    "train": "a routine local maintenance brief",
    "validation": "a staging incident triage brief",
    "test": "an independent release-readiness brief",
}

_BOUNDARY_PROBES: tuple[tuple[str, str, str | None, str], ...] = (
    ("trivial_conversation", "Say hello in one short sentence.", "DIRECT", "general"),
    ("factual_question", "What is a write-ahead log? Answer from established knowledge.", "DIRECT", "explanation"),
    ("current_information", "Find the current stable Python release from official sources.", "DELEGATE", "current_information_research"),
    ("repository_inspection", "Inspect this repository and identify where routing labels are stored.", "DELEGATE", "repository_inspection"),
    ("repository_modification", "Modify the repository parser and validate the change.", "DELEGATE", "repository_modification"),
    ("small_code_change", "Change one error message in the parser file and run its focused test.", "DELEGATE", "implementation"),
    ("multi_file_code_change", "Update the API, storage layer, and tests across multiple files, then verify the build.", "DELEGATE", "multi_step_execution"),
    ("bug_investigation", "Investigate the intermittent build failure using repository history and logs.", "DELEGATE", "tool_investigation"),
    ("build_test", "Run the project test suite and report the verified result.", "DELEGATE", "test_build_execution"),
    ("security_review", "Audit the authentication code in this repository for exploitable authorization weaknesses.", "DELEGATE", "security_review"),
    ("retrieval_research", "Research the latest official guidance and compare three primary sources.", "DELEGATE", "external_research"),
    ("tool_required", "Use the terminal to inspect the active service and its logs.", "DELEGATE", "tool_investigation"),
    ("multi_step_implementation", "First inspect the code, then implement the fix, run tests, and verify the package.", "DELEGATE", "multi_step_execution"),
    ("ambiguous", "Help me with the project if that seems useful.", None, "ambiguous"),
    ("complex_reasoning_no_execution", "Reason through the security trade-offs of capability systems without tools or external sources.", "DIRECT", "reasoning"),
    ("complex_execution_verification", "Diagnose the production-like failure, patch the repository, run build and tests, and verify recovery.", "DELEGATE", "system_investigation"),
)


def boundary_probes() -> list[dict[str, Any]]:
    probes: list[dict[str, Any]] = []
    for identifier, request, label, task_category in _BOUNDARY_PROBES:
        contract = decision_profile(request)
        contract["task_category"] = task_category
        probes.append({
            "probe_id": identifier,
            "request": request,
            "label": label,
            "split": "train",
            "task_category": task_category,
            "contract": contract,
            "contract_version": "phase-1-9-boundary-v1",
        })
    return probes


def _delegate_factories() -> tuple[tuple[str, Callable[[str], str]], ...]:
    return (
        ("repository_inspection", lambda subject: (
            f"Inspect the repository implementation of the {subject}, trace its callers, and report the actual control flow."
        )),
        ("file_lookup", lambda subject: (
            f"Locate the exact files and symbols that define the {subject}; return verified repository paths."
        )),
        ("implementation", lambda subject: (
            f"Implement a safe change to the {subject}, update focused tests, and preserve existing behavior."
        )),
        ("test_build_execution", lambda subject: (
            f"Run the focused tests and build for the {subject}, diagnose any failure, and verify the final result."
        )),
        ("tool_investigation", lambda subject: (
            f"Use the available terminal and logs to investigate the {subject}, reproduce the issue, and identify its root cause."
        )),
        ("external_research", lambda subject: (
            f"Research the current official guidance for the {subject} using live sources and cite the evidence."
        )),
        ("multi_source_verification", lambda subject: (
            f"Verify the current status of the {subject} against at least two independent authoritative sources."
        )),
        ("multi_step_execution", lambda subject: (
            f"First inspect the {subject}, then apply the required configuration change, run validation, and summarize the evidence."
        )),
        ("system_investigation", lambda subject: (
            f"Investigate the live system state for the {subject}, inspect relevant processes and logs, and confirm the diagnosis."
        )),
        ("noncoding_execution", lambda subject: (
            f"Open the required environment for the {subject}, collect its current state, perform the requested operation, and verify completion."
        )),
    )


def controlled_probes() -> list[dict[str, Any]]:
    """Return stable, independent probes with explicit held-out split contracts."""
    probes: list[dict[str, Any]] = []
    for split, topics in _DIRECT_TOPICS.items():
        templates = _DIRECT_TEMPLATES[split]
        for index, topic in enumerate(topics):
            category = DIRECT_CATEGORIES[index % len(DIRECT_CATEGORIES)]
            request = (
                templates[index % len(templates)].format(topic=topic)
                + f" Focus specifically on {_DIRECT_LENSES[index]}."
            )
            probes.append({
                "request": request,
                "label": "DIRECT",
                "split": split,
                "task_category": category,
                "contract": {
                    "repository_required": False,
                    "retrieval_required": False,
                    "tool_required": False,
                    "current_information_required": False,
                    "execution_required": False,
                    "modification_required": False,
                    "verification_required": False,
                    "multi_step_required": False,
                    "category": "reasoning" if category != "drafting" else "general",
                    "complexity": "medium" if category in {"reasoning", "conceptual_analysis"} else "low",
                    "task_category": category,
                },
            })
    factories = _delegate_factories()
    for split, subjects in _DELEGATE_SUBJECTS.items():
        repetitions = 1 if split != "train" else 1
        for round_index in range(repetitions):
            for subject in subjects:
                for category, factory in factories:
                    request = factory(f"{subject} scenario {round_index + 1}")
                    request += (
                        f" In {_SCENARIO_CONTEXT[split]}, treat "
                        f"{category.replace('_', ' ')} evidence as distinct from "
                        f"{_DIRECT_LENSES[(len(probes) + round_index) % len(_DIRECT_LENSES)]}; "
                        f"cover {_DELEGATE_DETAILS[subject]}."
                    )
                    contract = decision_profile(request)
                    contract.update({
                        "task_category": category,
                        "category": (
                            "research" if category in {
                                "external_research", "multi_source_verification"
                            } else "coding" if category in {
                                "repository_inspection", "file_lookup", "implementation",
                                "test_build_execution"
                            } else "general"
                        ),
                        "complexity": "high" if category in {
                            "multi_step_execution", "system_investigation"
                        } else "medium",
                    })
                    probes.append({
                        "request": request,
                        "label": "DELEGATE",
                        "split": split,
                        "task_category": category,
                        "contract": contract,
                    })
    probes.extend(boundary_probes())
    fingerprints = {request_fingerprint(str(probe["request"])) for probe in probes}
    if len(fingerprints) != len(probes):
        raise RuntimeError("probe generator produced duplicate requests")
    return probes


def import_controlled_probes(store: IntelligenceStore) -> dict[str, Any]:
    probes = controlled_probes()
    desired_record_ids = {
        "probe_" + hashlib.sha256(
            f"phase-1-9:{request_fingerprint(sanitize_request(str(probe['request']))[0])}".encode(
                "utf-8"
            )
        ).hexdigest()[:24]
        for probe in probes
    }
    removed = store.delete_stale_probe_records(desired_record_ids)
    created = 0
    existing = 0
    balance: Counter[str] = Counter()
    split_balance: dict[str, Counter[str]] = {
        "train": Counter(), "validation": Counter(), "test": Counter()
    }
    for probe in probes:
        safe, redacted = sanitize_request(str(probe["request"]))
        fingerprint = request_fingerprint(safe)
        record_id = "probe_" + hashlib.sha256(
            f"phase-1-9:{fingerprint}".encode("utf-8")
        ).hexdigest()[:24]
        contract = decision_profile(safe, probe["contract"])
        store.record_routing({
            "record_id": record_id,
            "source_kind": "probe_gold",
            "source_task_id": f"probe-contract-v1:{record_id}",
            "entrypoint": "controlled_probe",
            "decision_applied": False,
            "request_text": safe,
            "request_fingerprint": fingerprint,
            "group_fingerprint": fingerprint,
            "request_redacted": redacted,
            "request_length": len(safe),
            "estimated_tokens": (len(safe) + 3) // 4,
            "task_type": contract["task_category"],
            **contract,
            "repository_present": False,
            "project_fingerprint": None,
            "context_tokens": 0,
            "production_decision": None,
            "routing_reason": "probe_contract_ground_truth",
            "split_hint": probe["split"],
        })
        expected_label = probe.get("label")
        prior = store.record_label(record_id)
        if expected_label is None:
            if prior is not None:
                raise ValueError(f"ambiguous probe unexpectedly has a label: {record_id}")
            if record_id not in store.latest_reviews():
                store.exclude_record(
                    record_id,
                    source="probe_gold",
                    notes="Uncertain by the independently defined probe contract.",
                )
            existing += 1
            continue
        if prior is None:
            store.label_record(
                record_id,
                str(expected_label),
                source="probe_gold",
                notes="Label defined by the controlled task contract, not by any router.",
                confidence=1.0,
                labeling_method="probe_contract_v2",
            )
            created += 1
        elif prior["label"] == expected_label and prior["source"] == "probe_gold":
            existing += 1
        else:
            raise ValueError(f"probe identity collision for {record_id}")
        balance[str(expected_label)] += 1
        split_balance[str(probe["split"])][str(expected_label)] += 1
    return {
        "created": created,
        "existing": existing,
        "removedStale": removed,
        "count": created + existing,
        "uncertainCount": sum(probe.get("label") is None for probe in probes),
        "boundaryCoverage": [probe[0] for probe in _BOUNDARY_PROBES],
        "classBalance": dict(sorted(balance.items())),
        "splitClassBalance": {
            split: dict(sorted(values.items())) for split, values in split_balance.items()
        },
        "categoryCount": len(DIRECT_CATEGORIES) + len(DELEGATE_CATEGORIES),
    }
