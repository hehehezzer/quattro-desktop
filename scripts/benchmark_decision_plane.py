#!/usr/bin/env python3
"""Retired fixed-question decision benchmark; no provider or task activity.

Use benchmark_jev_live.py --decisions-stdin with model-authored v2 decisions
for current advisory transport measurements.
"""
import argparse
import json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    print(json.dumps({"status": "retired", "provider_attempted": False,
                      "reason": "static_decision_questionnaire_removed",
                      "replacement": "benchmark_jev_live.py --decisions-stdin"}))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
