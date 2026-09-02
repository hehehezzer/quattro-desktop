#!/usr/bin/env python3
"""Measure Quattro-owned context gating with synthetic, content-free fixtures.

The harness records counts only. Codex-owned system, skill, tool-schema, and
permission overhead is intentionally reported as unmeasured rather than read
from private requests.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from quattro_agent.routing_intelligence import context_load_plan, profile_task  # noqa: E402


FIXTURES = (
    ("hello", "reply with hello", 900),
    ("simple_clone", "Clone https://github.com/example/example into the default project directory.", 1_200),
    ("small_code_edit", "Fix the bounded null check bug in one parser and run tests", 1_200),
    ("normal_feature", "Implement a normal export feature and unit tests", 1_800),
    ("security_audit", "Review an intermittent authorization bypass without changing files", 2_200),
    ("frontend_design", "Design a frontend screenshot workflow and explain the visual hierarchy", 1_500),
    ("large_repository_analysis", "Analyze architecture across the whole repository without changing files", 4_000),
)

STATIC = {
    "memory_policy": 120,
    "mandatory_policy": 90,
    "coordination": 220,
    "delegation_policy": 120,
}


def measurement(name: str, prompt: str, retrieval_tokens: int) -> dict[str, object]:
    profile = profile_task(prompt)
    plan = context_load_plan(profile)
    user_tokens = max(1, (len(prompt) + 3) // 4)
    before = {
        "user_task": user_tokens,
        "retrieval": retrieval_tokens,
        **STATIC,
    }
    after = {
        "user_task": user_tokens,
        "retrieval": retrieval_tokens if plan.load_retrieval else 0,
        "memory_policy": STATIC["memory_policy"],
        "mandatory_policy": STATIC["mandatory_policy"],
        "coordination": STATIC["coordination"] if plan.load_coordination else 0,
        "delegation_policy": STATIC["delegation_policy"] if plan.load_delegation_policy else 0,
    }
    before_total = sum(before.values())
    after_total = sum(after.values())
    return {
        "name": name,
        "tier": profile.tier.value,
        "context_profile": plan.profile.value,
        "before": before,
        "after": after,
        "before_total": before_total,
        "after_total": after_total,
        "reduction": before_total - after_total,
        "reduction_percent": round((before_total - after_total) * 100 / before_total, 1),
        "codex_owned_overhead": "unmeasured",
    }


def main() -> int:
    print(json.dumps({
        "schema_version": 1,
        "measurement": "synthetic_content_free_quattro_owned_context",
        "fixtures": [measurement(*fixture) for fixture in FIXTURES],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
