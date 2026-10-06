#!/usr/bin/env python3
"""Retired historical static-routing benchmark; never submits provider requests.

Use benchmark_jev_live.py with an execution-model-authored v2 decision supplied
through its bounded stdin interface for provider transport measurements.
"""
import argparse
import json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    print(json.dumps({"status": "retired", "provider_attempted": False,
                      "reason": "static_routing_questionnaire_removed",
                      "replacement": "benchmark_jev_live.py --decisions-stdin"}))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
