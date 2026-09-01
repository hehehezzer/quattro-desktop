#!/usr/bin/env python3
"""Deterministic offline before/after evaluation for Quattro routing policy."""

from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from quattro_agent.routing_intelligence import profile_task


FIXTURES = (
    ("typo", "Fix a typo in README.md", "FAST"),
    ("rename", "Rename Foo to Bar in README; prose mentions authentication", "FAST"),
    ("small_bug", "Fix a bounded null check bug in one parser and run tests", "STANDARD"),
    ("feature", "Implement a normal export feature and tests", "STANDARD"),
    ("multi_file", "Implement a bounded multi-file feature across two modules", "STANDARD"),
    ("unknown_debug", "Investigate an intermittent unknown failure that cannot reproduce", "REASONING"),
    ("architecture", "Design the system architecture and trade-offs", "REASONING"),
    ("concurrency", "Fix a race condition and deadlock across workers", "REASONING"),
    ("security", "Fix an intermittent authorization bypass", "REASONING"),
    ("migration", "Migrate the database schema and backfill every row", "REASONING"),
    ("huge_context", "Analyze the entire repository with huge context before implementing", "REASONING"),
    ("docs", "Update the docs label from Old to New", "FAST"),
)

OLD_REASONING = re.compile(
    r"\b(?:architecture|security(?:[- ]critical)?|incident|production|concurren(?:cy|t)|"
    r"race condition|deadlock|data loss|migration|root cause|ambiguous|distributed|"
    r"cross[- ]cutting|large refactor)\b",
    re.IGNORECASE,
)
OLD_FAST = re.compile(
    r"\b(?:find|search|locate|list|read|inspect|summari[sz]e|explain|format|lint|"
    r"rename|typo|documentation|docs?|configuration|config|symbol|grep|deterministic|mechanical)\b",
    re.IGNORECASE,
)
OLD_NORMAL_WORK = re.compile(
    r"\b(?:implement|feature|debug|refactor|integration|test suite)\b", re.IGNORECASE
)
TIER_COST = {"FAST": 1.0, "STANDARD": 3.0, "REASONING": 8.0}
TIER_RANK = {"FAST": 0, "STANDARD": 1, "REASONING": 2}


def old_tier(prompt: str) -> str:
    if OLD_REASONING.search(prompt):
        return "REASONING"
    if OLD_FAST.search(prompt) and not OLD_NORMAL_WORK.search(prompt):
        return "FAST"
    return "STANDARD"


def metrics(predictions: list[str]) -> dict[str, float | int]:
    expected = [tier for _name, _prompt, tier in FIXTURES]
    correct = sum(actual == wanted for actual, wanted in zip(predictions, expected, strict=True))
    under = sum(
        TIER_RANK[actual] < TIER_RANK[wanted]
        for actual, wanted in zip(predictions, expected, strict=True)
    )
    over = sum(
        TIER_RANK[actual] > TIER_RANK[wanted]
        for actual, wanted in zip(predictions, expected, strict=True)
    )
    return {
        "fixture_accuracy": correct / len(FIXTURES),
        "incorrect_cheap_selections": under,
        "unnecessary_strong_selections": over,
        "average_tier_cost_proxy": sum(TIER_COST[tier] for tier in predictions) / len(predictions),
        "average_expected_completion_cost_proxy": sum(
            TIER_COST[actual]
            + (TIER_COST[wanted] * 1.5 if TIER_RANK[actual] < TIER_RANK[wanted] else 0)
            for actual, wanted in zip(predictions, expected, strict=True)
        ) / len(predictions),
        "escalation_need_proxy": under,
    }


def main() -> int:
    before = [old_tier(prompt) for _name, prompt, _tier in FIXTURES]
    after = [profile_task(prompt).tier.value for _name, prompt, _tier in FIXTURES]
    result = {
        "schemaVersion": 1,
        "kind": "offline-routing-policy-evaluation",
        "cases": len(FIXTURES),
        "before": metrics(before),
        "after": metrics(after),
        "rows": [
            {"name": name, "expected": expected, "before": old, "after": new}
            for (name, _prompt, expected), old, new in zip(FIXTURES, before, after, strict=True)
        ],
        "notMeasured": [
            "real validated task success",
            "actual provider/model cost",
            "provider concentration",
            "routing latency under production load",
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["after"]["fixture_accuracy"] >= result["before"]["fixture_accuracy"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
