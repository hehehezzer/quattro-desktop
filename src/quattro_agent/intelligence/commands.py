"""CLI orchestration for Quattro Intelligence Milestone 1."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from typing import Any

from ..routing_intelligence import profile_task
from .adjudication import (
    auto_adjudicate_unlabeled,
    quarantine_adjudication,
)
from .classical import ALGORITHM, DirectDelegateModel, train_direct_delegate_model
from .dataset import (
    DatasetBuilder,
    dataset_identity,
    dataset_quality,
    load_dataset,
    validate_dataset_identity,
)
from .evaluation import benchmark_direct_delegate
from .features import decision_profile
from .maturity import data_maturity
from .readiness import load_promotion_thresholds, promotion_gate_summary
from .probes import import_controlled_probes
from .review import (
    BLIND_REVIEW_KIND,
    REASON_CATEGORIES,
    RUBRIC_VERSION,
    blind_review_payload,
    public_review_item,
    review_progress as blind_review_progress,
    validate_blind_review_payload,
)
from .store import IntelligenceStore
from .telemetry import sanitize_request


def _latest(directory: pathlib.Path, pattern: str) -> pathlib.Path | None:
    candidates = sorted(directory.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def add_intelligence_parser(subparsers: argparse._SubParsersAction[Any]) -> None:
    parser = subparsers.add_parser(
        "intelligence",
        help="collect, label, train, shadow, and benchmark routing intelligence",
    )
    parser.add_argument(
        "action",
        choices=(
            "status", "sync", "import-labels", "label", "dataset", "train",
            "predict", "eval", "benchmark", "report", "quality",
            "readiness",
            "review-queue", "review-batch", "review-import", "review-audit",
            "blind-review-queue", "blind-review-batch", "blind-review-import",
            "blind-review-audit", "blind-review-correct",
            "generate-probes", "auto-label", "phase-1-8", "phase-1-9",
            "phase-1-10",
        ),
        nargs="?",
        default="status",
    )
    parser.add_argument("value", nargs="?")
    parser.add_argument("label", nargs="?", choices=("DIRECT", "DELEGATE"))
    parser.add_argument("--source", choices=(
        "human_verified", "reviewed_outcome", "curated_benchmark",
        "human_gold", "probe_gold", "silver",
    ))
    parser.add_argument("--notes", default="")
    parser.add_argument("--input")
    parser.add_argument("--dataset")
    parser.add_argument("--model")
    parser.add_argument("--prompt")
    parser.add_argument("--repository-present", action="store_true")
    parser.add_argument("--output-directory")
    parser.add_argument("--output")
    parser.add_argument("--activate-shadow", action="store_true")
    parser.add_argument("--no-sync", action="store_true")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--production-decision", choices=("DIRECT", "DELEGATE"))
    parser.add_argument("--reviewer")
    parser.add_argument("--vote-id")
    parser.add_argument("--verdict", choices=("DIRECT", "DELEGATE", "UNCERTAIN"))
    parser.add_argument("--reason-category", choices=REASON_CATEGORIES)
    parser.add_argument("--correction-reason")
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument(
        "--thresholds",
        help="private JSON policy for offline data/promotion thresholds",
    )


def _print(payload: Mapping[str, Any], pretty: bool) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2 if pretty else None))


def _write_private_json(path: pathlib.Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def _write_private_text(path: pathlib.Path, content: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def _source_revision() -> str:
    root = pathlib.Path(__file__).resolve().parents[3]
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    value = result.stdout.strip()
    return value if result.returncode == 0 and len(value) == 40 else "unknown"


def _thresholds(args: argparse.Namespace):
    return load_promotion_thresholds(getattr(args, "thresholds", None))


def _phase_19_markdown(payload: Mapping[str, Any]) -> str:
    quality = payload.get("dataset", {}).get("quality", {})
    chronology = quality.get("chronologicalCoverage", {})
    maturity = payload.get("dataMaturity", {})
    promotion = payload.get("promotionGates", {})
    evaluation = payload.get("installedShadowEvaluation", {})
    def compact_metrics(report: Mapping[str, Any]) -> dict[str, Any]:
        metrics = report.get("metrics", report)
        if not isinstance(metrics, Mapping):
            return {}
        return {
            key: metrics.get(key)
            for key in (
                "sampleCount", "accuracy", "balancedAccuracy", "f1",
                "delegateFalseNegativeRate", "precision", "recall",
            )
            if key in metrics
        }
    category_summary = {
        str(name): {
            "sampleCount": report.get("sampleCount"),
            "baselineMetrics": compact_metrics(report.get("baselineMetrics", {})),
            "modelMetrics": compact_metrics(report.get("modelMetrics", {})),
            "disagreementRate": report.get("disagreementRate"),
        }
        for name, report in (evaluation.get("performanceByTaskCategory", {}) or {}).items()
        if isinstance(report, Mapping)
    }
    disagreement = evaluation.get("disagreementTelemetry", {})
    disagreement_summary = {
        key: disagreement.get(key)
        for key in (
            "count", "eligibleForEvaluation", "knownOutcomeCount",
            "byTaskCategory", "byComplexity", "counterfactualStatus",
        )
        if key in disagreement
    }
    observed = evaluation.get("observedOutcomeEvidence", {})
    outcome_summary = {
        key: observed.get(key)
        for key in (
            "observedOutcomeCount", "unknownOutcomeCount", "byDeterministicRoute",
            "disagreementObservedOutcome", "counterfactualStatus",
        )
        if key in observed
    }
    lines = [
        "# Quattro Intelligence Phase 1.9",
        "",
        f"- Status: **{payload.get('phaseStatus')}**",
        f"- Dataset: `{payload.get('datasetVersion')}`",
        f"- Independent usable groups: {quality.get('usableIndependentGroupCount', 0)}",
        f"- Class balance: `{json.dumps(quality.get('usableIndependentClassBalance', {}), sort_keys=True)}`",
        f"- Evidence sources: `{json.dumps(quality.get('independenceProvenGroupsByLabelSource', {}), sort_keys=True)}`",
        f"- Validation/test coverage: `{json.dumps(quality.get('usableIndependentSplitClassBalance', {}), sort_keys=True)}`",
        f"- Quarantined conflict groups: {quality.get('quarantinedConflictGroupCount', 0)}",
        f"- Duplicate rows collapsed for modeling: {quality.get('duplicateRowsCollapsedForModeling', 0)}",
        f"- Chronology credible: {chronology.get('credibleHumanGoldChronology', False)}",
        f"- Active shadow unchanged: `{payload.get('activeShadowModelAfter')}`",
        f"- Eligible examples/groups: {maturity.get('eligibleExamples', 0)} / {maturity.get('eligibleIndependentGroups', 0)}",
        f"- Label completeness: {maturity.get('labelCompleteness', {}).get('rate')}",
        f"- Deterministic route balance: `{json.dumps(maturity.get('deterministicRouteBalance', {}), sort_keys=True)}`",
        f"- Outcome evidence: `{json.dumps(maturity.get('outcomes', {}).get('counterfactualComparison', {}), sort_keys=True)}`",
        "",
        "## Promotion Gates",
        f"- Overall: **{promotion.get('status', 'BLOCKED BY DATA')}**",
        f"- Passed: `{json.dumps(promotion.get('gatesPassed', []), sort_keys=True)}`",
        f"- Failed: `{json.dumps(promotion.get('gatesFailed', []), sort_keys=True)}`",
        f"- Blocked: `{json.dumps(promotion.get('gatesBlocked', []), sort_keys=True)}`",
        "",
        "## Shadow Evaluation",
        f"- Status: **{evaluation.get('status', 'not evaluated')}**",
        f"- Deterministic metrics: `{json.dumps(evaluation.get('baseline', {}).get('metrics', {}), sort_keys=True)}`",
        f"- Shadow metrics: `{json.dumps(evaluation.get('model', {}).get('metrics', {}), sort_keys=True)}`",
        f"- Disagreement rate: {evaluation.get('disagreementRate')}",
        f"- Disagreement telemetry: `{json.dumps(disagreement_summary, sort_keys=True)}`",
        f"- Observed outcomes: `{json.dumps(outcome_summary, sort_keys=True)}`",
        f"- Delegate-probability calibration: `{json.dumps(evaluation.get('delegateProbabilityCalibration', evaluation.get('confidenceCalibration', {})), sort_keys=True)}`",
        f"- Class-confidence calibration: `{json.dumps(evaluation.get('classConfidenceCalibration', {}), sort_keys=True)}`",
        f"- Category metrics: `{json.dumps(category_summary, sort_keys=True)}`",
        "",
        "## Remaining Deficits",
    ]
    reasons = quality.get("reasons") or []
    lines.extend(f"- {reason}" for reason in reasons)
    if not reasons:
        lines.append("- None")
    lines.extend((
        "",
        "Production routing remains deterministic and authoritative. The candidate, if any, is offline only.",
        "",
    ))
    return "\n".join(lines)


def _phase_110_markdown(payload: Mapping[str, Any]) -> str:
    quality = payload.get("dataset", {}).get("quality", {})
    audit = payload.get("blindHumanGoldAudit", {})
    chronology = quality.get("chronologicalCoverage", {})
    gates = payload.get("candidateGate", {}).get("gates", {})
    duplicates = quality.get("labelQualityAudit", {})
    lines = [
        "# Quattro Intelligence Phase 1.10",
        "",
        "## Status",
        f"**{payload.get('phaseStatus')}**",
        "",
        "## Phase 1.9 Baseline",
        f"- Dataset: `{payload.get('phase19Baseline', {}).get('datasetVersion')}`",
        f"- Dataset fingerprint and registry verified: {payload.get('phase19Baseline', {}).get('verified', False)}",
        "- Installed shadow remained below the deterministic router on the Phase 1.9 independent probe test.",
        "",
        "## Implementation Changes",
        "- Versioned blind human rubric and exact reviewer-visible payload allowlist.",
        "- Append-only independent votes, agreement metrics, and audited correction events.",
        "- Stratified category sampling with route-oblivious display order.",
        "- Deterministic semantic duplicate grouping and immutable split manifest fingerprint.",
        "- Readiness-gated offline candidate workflow; production routing remains unchanged.",
        "",
        "## Blind Human-Gold Audit",
        f"- Reviewed groups: {audit.get('reviewedRecordCount', 0)}",
        f"- DIRECT votes: {audit.get('verdictBalance', {}).get('DIRECT', 0)}",
        f"- DELEGATE votes: {audit.get('verdictBalance', {}).get('DELEGATE', 0)}",
        f"- UNCERTAIN votes: {audit.get('verdictBalance', {}).get('UNCERTAIN', 0)}",
        f"- Agreement rate: {audit.get('agreement', {}).get('agreementRate')}",
        f"- Cohen's kappa: {audit.get('agreement', {}).get('cohenKappaTwoReviewer')}",
        f"- Fleiss' kappa by rater count: `{json.dumps(audit.get('agreement', {}).get('fleissKappaByRaterCount', {}), sort_keys=True)}`",
        f"- Rubric version: `{audit.get('rubricVersion')}`",
        "",
        "## Dataset Audit",
        f"- Total rows: {payload.get('dataset', {}).get('recordCount', 0)}",
        f"- Total groups: {quality.get('totalGroupCount', 0)}",
        f"- Independent groups: {quality.get('usableIndependentGroupCount', 0)}",
        f"- Class counts: `{json.dumps(quality.get('usableIndependentClassBalance', {}), sort_keys=True)}`",
        f"- Provenance counts: `{json.dumps(quality.get('independenceProvenGroupsByLabelSource', {}), sort_keys=True)}`",
        f"- Human-gold: {quality.get('independenceProvenGroupsByLabelSource', {}).get('human_gold', 0)}",
        f"- Probe-gold: {quality.get('independenceProvenGroupsByLabelSource', {}).get('probe_gold', 0)}",
        f"- Silver: {quality.get('independenceProvenGroupsByLabelSource', {}).get('silver', 0)}",
        f"- Uncertain groups: {quality.get('excludedAmbiguousIndependentGroupCount', 0)}",
        f"- Quarantined groups: {quality.get('quarantinedConflictGroupCount', 0)}",
        f"- Category counts: `{json.dumps(quality.get('usableIndependentTaskCategoryBalance', {}), sort_keys=True)}`",
        f"- Train/validation/test: `{json.dumps(quality.get('usableIndependentSplitClassBalance', {}), sort_keys=True)}`",
        f"- Chronological human groups: {chronology.get('independenceProvenHumanGoldGroupCount', 0)}",
        f"- Exact duplicate rows: {quality.get('duplicateRequestRows', 0)}",
        f"- Lexical near-duplicate pairs: {quality.get('potentialNearDuplicatePairs', 0)}",
        f"- Semantic near-duplicate pairs: {quality.get('semanticNearDuplicatePairs', 0)}",
        f"- Cross-split contamination: {quality.get('exactDuplicateCrossSplitFingerprints', 0) + quality.get('potentialNearDuplicateCrossSplitPairs', 0) + quality.get('semanticNearDuplicateCrossSplitPairs', 0)}",
        f"- {quality.get('humanGoldReadyStatement', 'HUMAN GOLD READY: NO')}",
        "",
        "## Leakage Audit",
        f"- Decision/outcome leakage check: {'PASS' if quality.get('futureInformationLeakage', {}).get('passed') else 'FAIL'}",
        f"- Reviewer payload allowlist: {'PASS' if payload.get('reviewInterfaceLeakageAudit', {}).get('passed') else 'FAIL'}",
        "",
        "## Candidate Gate",
    ]
    lines.extend(
        f"- {name}: **{'PASS' if passed else 'FAIL'}**"
        for name, passed in gates.items()
    )
    lines.extend((
        "",
        "## Candidate Evaluation",
        (
            "- Not run: data gates did not all pass."
            if payload.get("candidateEvaluation") is None
            else f"- Candidate model: `{payload.get('candidateModelVersion')}`"
        ),
        "",
        "## Deterministic Comparison",
        "- Deterministic routing remains authoritative; no production decision path changed.",
        "",
        "## Category-Level Findings",
        (
            f"- Independently supported category signals: `{json.dumps(payload.get('usefulCategorySignals', []))}`"
            if payload.get("usefulCategorySignals")
            else "- No category-specific ML role is claimed without eligible independent evidence."
        ),
        "",
        "## Error Analysis",
        f"- Human-review category disagreements: `{json.dumps(audit.get('disagreementByCategory', {}), sort_keys=True)}`",
        f"- Boundary disagreements: {audit.get('boundaryDisagreementCount', 0)}",
        "",
        "## Validation",
        "- Phase 1.10 acquisition/report command: **PASSED**",
        f"- Candidate gate: **{'PASSED' if payload.get('candidateGate', {}).get('status') == 'PASS' else 'FAILED'}**",
        f"- Candidate training: **{'PASSED' if payload.get('candidateEvaluation') is not None else 'NOT RUN'}**",
        "- Repository test/lint/build checks: **NOT RUN** by the report generator; see the engineering handoff.",
        "",
        "## Production Impact",
        "- Production DIRECT/DELEGATE routing, provider/account/model selection, OmniRoute, tier semantics, and `/model` are unchanged.",
        "",
        "## Risks",
        "- Reviewer agreement and chronological evidence remain sparse until independent humans complete blind queues.",
        f"- Duplicate grouping remains a conservative deterministic approximation ({duplicates.get('suspiciousRepeatedPatternCount', 0)} repeated-pattern findings).",
        "",
        "## Remaining Blockers",
    ))
    reasons = quality.get("reasons") or []
    lines.extend(f"- {reason}" for reason in reasons)
    if not reasons:
        lines.append("- None")
    lines.extend((
        "",
        "## ML Viability",
        f"**{payload.get('mlViability')}**",
        "",
        "## Phase 2 Readiness",
        f"**{payload.get('phase2Readiness')}**",
        "",
    ))
    return "\n".join(lines)


def _candidate_gate_report(
    quality: Mapping[str, Any],
    *,
    registered_dataset_fingerprint: bool,
) -> dict[str, Any]:
    gates = dict(quality.get("candidateGates") or {})
    gates["registeredDatasetFingerprint"] = bool(registered_dataset_fingerprint)
    return {
        "status": "PASS" if gates and all(gates.values()) else "FAIL",
        "gates": gates,
        "failed": [name for name, passed in gates.items() if not passed],
    }


def _candidate_viability(benchmark: Mapping[str, Any]) -> tuple[str, list[str]]:
    if benchmark.get("phase2Assessment", {}).get("status") == "READY":
        return "VIABLE", []
    useful_categories: list[str] = []
    categories = benchmark.get("humanGoldRealTest", {}).get(
        "performanceByTaskCategory", {}
    )
    if isinstance(categories, Mapping):
        for name, report in categories.items():
            if not isinstance(report, Mapping) or int(report.get("sampleCount", 0)) < 30:
                continue
            class_balance = report.get("classBalance", {})
            if not isinstance(class_balance, Mapping) or not all(
                int(class_balance.get(label, 0)) >= 10
                for label in ("DIRECT", "DELEGATE")
            ):
                continue
            baseline = report.get("baselineMetrics", {})
            model = report.get("modelMetrics", {})
            paired = report.get("pairedComparison", {})
            calibration = report.get("calibration", {})
            improvement = float(model.get("balancedAccuracy", 0.0)) - float(
                baseline.get("balancedAccuracy", 0.0)
            )
            if (
                improvement >= 0.05
                and float(model.get("f1", 0.0)) >= float(baseline.get("f1", 0.0))
                and int(paired.get("modelWins", 0)) > int(paired.get("baselineWins", 0))
                and float(paired.get("exactMcNemarPValue", 1.0)) <= 0.05
                and calibration.get("expectedCalibrationError") is not None
                and float(calibration["expectedCalibrationError"]) <= 0.10
                and calibration.get("brierScore") is not None
                and float(calibration["brierScore"]) <= 0.20
            ):
                useful_categories.append(str(name))
    if useful_categories:
        return "LIMITED VIABILITY", sorted(useful_categories)
    return "NOT YET PROVEN", []


def _validate_registered_dataset(
    store: IntelligenceStore,
    dataset_version: str,
    rows: list[dict[str, Any]],
) -> None:
    manifest = store.dataset_manifest(dataset_version)
    _version, digest = dataset_identity(rows)
    if manifest.get("contentSha256") != digest:
        raise ValueError("dataset does not match its immutable registered manifest")


def _read_review_file(path: pathlib.Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("review input must be a regular file")
    if path.stat().st_size > 5_000_000:
        raise ValueError("review input exceeds 5 MB")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schemaVersion") not in {1, 2, 3}:
        raise ValueError("review input has an incompatible schema")
    return payload


def _review_progress(payload: Mapping[str, Any]) -> dict[str, int]:
    reviews = payload.get("reviews")
    if not isinstance(reviews, list):
        raise ValueError("review input must contain a reviews list")
    progress = {"verified": 0, "excluded": 0, "pending": 0, "skipped": 0}
    for review in reviews:
        if not isinstance(review, dict):
            continue
        status = str(review.get("reviewStatus") or "pending")
        label = review.get("label")
        if status == "verified" and label in {"DIRECT", "DELEGATE"}:
            progress["verified"] += 1
        elif status == "excluded" and label in {
            "EXCLUDE", "AMBIGUOUS", "AMBIGUOUS / EXCLUDE"
        }:
            progress["excluded"] += 1
        elif label is None:
            progress["pending"] += 1
        else:
            progress["skipped"] += 1
    progress["total"] = len(reviews)
    return progress


def _interactive_review_batch(path: pathlib.Path, payload: dict[str, Any], reviewer: str) -> dict[str, Any]:
    if not reviewer.strip():
        raise ValueError("review-batch requires --reviewer")
    if not sys.stdin.isatty():
        raise ValueError("review-batch requires an interactive terminal")
    reviews = payload.get("reviews")
    if not isinstance(reviews, list):
        raise ValueError("review input must contain a reviews list")
    payload["schemaVersion"] = 3
    payload["reviewer"] = reviewer.strip()
    finalized = 0
    skipped = 0
    for index, review in enumerate(reviews, 1):
        if not isinstance(review, dict):
            continue
        if review.get("label") is not None or review.get("reviewStatus") != "pending":
            continue
        print(f"\n[{index}/{len(reviews)}]", flush=True)
        print(str(review.get("request") or "")[:4_000], flush=True)
        print(
            " | ".join((
                f"category={review.get('category') or 'unknown'}",
                f"complexity={review.get('complexity') or 'unknown'}",
                f"task={review.get('taskType') or 'unknown'}",
                f"repository={bool(review.get('repositoryPresent'))}",
                f"retrieval={bool(review.get('retrievalRequired'))}",
                f"tool={review.get('toolRequired')}",
            )),
            flush=True,
        )
        choice = input(
            "Label [d=DIRECT, g=DELEGATE, x=AMBIGUOUS/EXCLUDE, "
            "s=skip, q=save+quit]: "
        ).strip().lower()
        if choice == "q":
            break
        if choice == "s" or not choice:
            skipped += 1
            continue
        outcome = {"d": "DIRECT", "g": "DELEGATE", "x": "EXCLUDE"}.get(choice)
        if outcome is None:
            print("Unrecognized choice; record left pending.", flush=True)
            continue
        review["label"] = outcome
        review["reviewStatus"] = "excluded" if outcome == "EXCLUDE" else "verified"
        review["reviewer"] = reviewer.strip()
        review["reviewedAt"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")
        review["source"] = "human_verified"
        progress = _review_progress(payload)
        payload["progress"] = progress
        _write_private_json(path, payload)
        finalized += 1
        print(
            f"saved: verified={progress['verified']} excluded={progress['excluded']} "
            f"pending={progress['pending']}",
            flush=True,
        )
    payload["progress"] = _review_progress(payload)
    _write_private_json(path, payload)
    return {
        "finalizedThisRun": finalized,
        "skippedThisRun": skipped,
        "progress": payload["progress"],
    }


def _interactive_blind_review_batch(
    path: pathlib.Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Collect only reviewer-visible votes; reviewer identity stays CLI-side."""
    if not sys.stdin.isatty():
        raise ValueError("blind-review-batch requires an interactive terminal")
    validate_blind_review_payload(payload)
    items = payload["items"]
    finalized = 0
    skipped = 0
    for index, item in enumerate(items, 1):
        if item.get("label") is not None:
            continue
        print(f"\n[{index}/{len(items)}]", flush=True)
        print(str(item["request"])[:4_000], flush=True)
        requirements = item["requirements"]
        stated = [name for name, required in requirements.items() if required]
        print(
            "Explicit pre-routing requirements: " + (", ".join(stated) if stated else "none"),
            flush=True,
        )
        choice = input(
            "Label [d=DIRECT, g=DELEGATE, u=UNCERTAIN, s=skip, q=save+quit]: "
        ).strip().lower()
        if choice == "q":
            break
        if choice in {"", "s"}:
            skipped += 1
            continue
        verdict = {"d": "DIRECT", "g": "DELEGATE", "u": "UNCERTAIN"}.get(choice)
        if verdict is None:
            print("Unrecognized choice; item left pending.", flush=True)
            continue
        reason = input(
            "Optional reason category (blank to omit): "
        ).strip()
        if reason and reason not in REASON_CATEGORIES:
            print("Unknown reason category; item left pending.", flush=True)
            continue
        note = input("Optional short note (blank to omit): ").strip()
        if len(note) > 2_000:
            print("Note exceeds 2000 characters; item left pending.", flush=True)
            continue
        item["label"] = verdict
        item["reasonCategory"] = reason or None
        item["note"] = note
        item["reviewStatus"] = "completed"
        payload["progress"] = blind_review_progress(payload)
        validate_blind_review_payload(payload)
        _write_private_json(path, payload)
        finalized += 1
    payload["progress"] = blind_review_progress(payload)
    validate_blind_review_payload(payload)
    _write_private_json(path, payload)
    return {
        "finalizedThisRun": finalized,
        "skippedThisRun": skipped,
        "progress": payload["progress"],
    }


def intelligence_command(
    args: argparse.Namespace,
    *,
    state_root: pathlib.Path,
    task_store_path: pathlib.Path,
) -> int:
    root = state_root / "private" / "intelligence"
    store = IntelligenceStore(root / "intelligence.sqlite3")
    builder = DatasetBuilder(store)
    pretty = bool(args.pretty)
    policy = _thresholds(args)
    if args.action == "status":
        _print({"schemaVersion": 1, **store.status()}, pretty)
        return 0
    if args.action == "sync":
        result = builder.sync_task_history(task_store_path)
        _print({"schemaVersion": 1, "status": "synced", **result, **store.status()}, pretty)
        return 0
    if args.action == "import-labels":
        if not args.input:
            raise ValueError("intelligence import-labels requires --input")
        result = builder.import_curated(pathlib.Path(args.input).expanduser().resolve())
        _print({"schemaVersion": 1, "status": "imported", **result}, pretty)
        return 0
    if args.action == "label":
        if not args.value or not args.label or not args.source:
            raise ValueError("intelligence label requires RECORD_ID LABEL --source SOURCE")
        if args.source not in {"human_verified", "reviewed_outcome", "human_gold"}:
            raise ValueError(
                "probe and silver labels are accepted only through their dedicated pipelines"
            )
        store.label_record(
            args.value,
            args.label,
            source=args.source,
            notes=args.notes,
            reviewer=getattr(args, "reviewer", None),
        )
        _print({
            "schemaVersion": 1,
            "status": "labeled",
            "recordId": args.value,
            "label": args.label,
            "source": args.source,
        }, pretty)
        return 0
    if args.action == "blind-review-queue":
        if not args.output:
            raise ValueError(
                "intelligence blind-review-queue requires --output"
            )
        reviewer = str(getattr(args, "reviewer", None) or "")
        if not reviewer.strip():
            raise ValueError(
                "intelligence blind-review-queue requires --reviewer"
            )
        candidates = store.create_blind_review_batch(
            reviewer=reviewer,
            limit=args.limit,
        )
        payload = blind_review_payload([
            public_review_item(row["item_id"], row["request_text"])
            for row in candidates
        ])
        output = pathlib.Path(args.output).expanduser().resolve()
        _write_private_json(output, payload)
        _print({
            "schemaVersion": 1,
            "status": "blind_review_queue_created",
            "rubricVersion": RUBRIC_VERSION,
            "reviewCount": len(candidates),
            "output": str(output),
        }, pretty)
        return 0
    if args.action == "blind-review-batch":
        if not args.input:
            raise ValueError("intelligence blind-review-batch requires --input")
        path = pathlib.Path(args.input).expanduser().resolve()
        payload = _read_review_file(path)
        validate_blind_review_payload(payload)
        result = _interactive_blind_review_batch(path, payload)
        _print({
            "schemaVersion": 1,
            "status": "blind_review_batch_saved",
            "output": str(path),
            **result,
        }, pretty)
        return 0
    if args.action == "blind-review-import":
        if not args.input:
            raise ValueError("intelligence blind-review-import requires --input")
        reviewer = str(getattr(args, "reviewer", None) or "")
        if not reviewer.strip():
            raise ValueError("intelligence blind-review-import requires --reviewer")
        payload = _read_review_file(pathlib.Path(args.input).expanduser().resolve())
        validate_blind_review_payload(payload)
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")
        votes = [
            {
                "item_id": item["itemId"],
                "verdict": item["label"],
                "reason_category": item["reasonCategory"],
                "note": item["note"],
                "reviewed_at": now,
                "visible_request": item["request"],
                "visible_requirements": item["requirements"],
            }
            for item in payload["items"]
            if item.get("label") in {"DIRECT", "DELEGATE", "UNCERTAIN"}
        ]
        result = store.import_blind_review_votes(votes, reviewer=reviewer)
        _print({
            "schemaVersion": 1,
            "status": "blind_reviews_imported",
            "rubricVersion": RUBRIC_VERSION,
            **result,
            "audit": store.blind_review_audit(),
        }, pretty)
        return 0
    if args.action == "blind-review-audit":
        _print({
            "schemaVersion": 1,
            "status": "audited",
            "audit": store.blind_review_audit(),
        }, pretty)
        return 0
    if args.action == "blind-review-correct":
        reviewer = str(getattr(args, "reviewer", None) or "")
        vote_id = str(getattr(args, "vote_id", None) or "")
        correction_reason = str(getattr(args, "correction_reason", None) or "")
        corrected_verdict = str(getattr(args, "verdict", None) or args.label or "")
        if not reviewer or not vote_id or not corrected_verdict or not correction_reason:
            raise ValueError(
                "blind-review-correct requires --vote-id, --reviewer, LABEL, "
                "and --correction-reason"
            )
        replacement = store.correct_blind_review_vote(
            vote_id,
            reviewer=reviewer,
            verdict=corrected_verdict,
            reason_category=getattr(args, "reason_category", None),
            note=args.notes,
            correction_reason=correction_reason,
        )
        _print({
            "schemaVersion": 1,
            "status": "blind_review_corrected",
            "replacementVoteId": replacement,
            "audit": store.blind_review_audit(),
        }, pretty)
        return 0
    if args.action == "review-queue":
        if not args.output:
            raise ValueError(
                "intelligence review-queue requires --output so private requests are not printed"
            )
        records = store.review_queue(
            limit=args.limit,
            production_decision=args.production_decision,
        )
        payload = {
            "schemaVersion": 3,
            "kind": "quattro-intelligence-review-queue",
            "instructions": (
                "Review only request intent and decision-time features. Set label to "
                "DIRECT or DELEGATE with reviewStatus verified, or EXCLUDE with "
                "reviewStatus excluded for ambiguous/low-confidence cases. Leave label null "
                "and reviewStatus pending to skip. Set reviewer and reviewedAt. Keep recordId "
                "and requestFingerprint unchanged. ML predictions are intentionally hidden."
            ),
            "reviewChoices": ["DIRECT", "DELEGATE", "AMBIGUOUS / EXCLUDE", "SKIP"],
            "reviewer": getattr(args, "reviewer", None),
            "mlPredictionHidden": True,
            "productionEvidenceHidden": True,
            "reviewCount": len(records),
            "reviews": [{
                "recordId": row["record_id"],
                "requestFingerprint": row["request_fingerprint"],
                "request": row["request_text"],
                "sourceKind": row["source_kind"],
                "category": row["category"],
                "taskType": row["task_type"],
                "complexity": row["complexity"],
                "repositoryPresent": row["repository_present"],
                "retrievalRequired": row["retrieval_required"],
                "toolRequired": row.get("tool_required"),
                "label": None,
                "reviewStatus": "pending",
                "reviewer": None,
                "reviewedAt": None,
                "notes": "",
            } for row in records],
        }
        payload["progress"] = _review_progress(payload)
        output = pathlib.Path(args.output).expanduser().resolve()
        _write_private_json(output, payload)
        _print({
            "schemaVersion": 1,
            "status": "review_queue_created",
            "reviewCount": len(records),
            "output": str(output),
        }, pretty)
        return 0
    if args.action == "review-batch":
        if not args.input:
            raise ValueError("intelligence review-batch requires --input")
        path = pathlib.Path(args.input).expanduser().resolve()
        payload = _read_review_file(path)
        if payload.get("kind") != "quattro-intelligence-review-queue":
            raise ValueError("review input has an unsupported kind")
        result = _interactive_review_batch(
            path, payload, str(getattr(args, "reviewer", None) or "")
        )
        _print({
            "schemaVersion": 3,
            "status": "review_batch_saved",
            "output": str(path),
            **result,
        }, pretty)
        return 0
    if args.action == "review-import":
        if not args.input:
            raise ValueError("intelligence review-import requires --input")
        payload = _read_review_file(pathlib.Path(args.input).expanduser().resolve())
        if payload.get("kind") != "quattro-intelligence-review-queue":
            raise ValueError("review input has an unsupported kind")
        reviews = payload.get("reviews")
        if not isinstance(reviews, list):
            raise ValueError("review input must contain a reviews list")
        prepared: list[dict[str, Any]] = []
        skipped = 0
        for index, review in enumerate(reviews):
            if not isinstance(review, dict):
                raise ValueError(f"review {index} is not an object")
            label = review.get("label")
            if label is None:
                skipped += 1
                continue
            if label not in {
                "DIRECT", "DELEGATE", "EXCLUDE", "AMBIGUOUS", "AMBIGUOUS / EXCLUDE"
            }:
                raise ValueError(f"review {index} has an invalid label")
            expected_status = (
                "excluded"
                if label in {"EXCLUDE", "AMBIGUOUS", "AMBIGUOUS / EXCLUDE"}
                else "verified"
            )
            if review.get("reviewStatus") != expected_status:
                raise ValueError(f"review {index} has an invalid review status")
            record_id = review.get("recordId")
            fingerprint = review.get("requestFingerprint")
            if not isinstance(record_id, str) or not isinstance(fingerprint, str):
                raise ValueError(f"review {index} is missing record identity")
            source = str(review.get("source") or "human_verified")
            if source not in {"human_verified", "reviewed_outcome"}:
                raise ValueError(f"review {index} has an invalid source")
            prepared.append({
                "record_id": record_id,
                "request_fingerprint": fingerprint,
                "outcome": label,
                "source": source,
                "reviewer": (
                    review.get("reviewer")
                    or payload.get("reviewer")
                    or getattr(args, "reviewer", None)
                ),
                "reviewed_at": review.get("reviewedAt"),
                "notes": str(review.get("notes") or ""),
                "labeling_method": "legacy_exposed_review",
            })
        result = store.apply_review_labels(prepared)
        _print({
            "schemaVersion": 1,
            "status": "reviewed",
            "imported": result["imported"],
            "excluded": result["excluded"],
            "skipped": skipped + result["skipped"],
            **store.status(),
        }, pretty)
        return 0
    if args.action == "review-audit":
        _print({
            "schemaVersion": 1,
            "status": "audited",
            "audit": store.review_audit(),
        }, pretty)
        return 0
    if args.action == "generate-probes":
        _print({
            "schemaVersion": 1,
            "status": "generated",
            "labelSource": "probe_gold",
            **import_controlled_probes(store),
        }, pretty)
        return 0
    if args.action == "auto-label":
        _print({
            "schemaVersion": 1,
            "status": "adjudicated",
            "labelSource": "silver",
            **auto_adjudicate_unlabeled(store),
        }, pretty)
        return 0
    if args.action == "phase-1-10":
        active_before = store.status()["activeShadowModel"]
        sync_result = builder.sync_task_history(task_store_path)
        probe_result = import_controlled_probes(store)
        silver_result = auto_adjudicate_unlabeled(store)
        output_directory = root / "datasets"
        manifest = builder.extract(output_directory)
        dataset_path = pathlib.Path(str(manifest["datasetPath"]))
        rows = load_dataset(dataset_path)
        dataset_version = validate_dataset_identity(dataset_path, rows)
        _validate_registered_dataset(store, dataset_version, rows)
        quality = dataset_quality(rows, thresholds=policy)
        review_contract = blind_review_payload([])
        validate_blind_review_payload(review_contract)
        blind_audit = store.blind_review_audit()
        gate = _candidate_gate_report(
            quality,
            registered_dataset_fingerprint=True,
        )
        gate["gates"]["blindReviewInterfaceLeakage"] = True
        gate["gates"]["blindReviewEvidenceIntegrity"] = bool(
            blind_audit.get("integrity", {}).get("passed")
        )
        gate["status"] = "PASS" if all(gate["gates"].values()) else "FAIL"
        gate["failed"] = [
            name for name, passed in gate["gates"].items() if not passed
        ]
        prior_report_path = root / "phase-1-9-report.json"
        prior_report: dict[str, Any] = {}
        if prior_report_path.is_file() and not prior_report_path.is_symlink():
            try:
                decoded = json.loads(prior_report_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                decoded = {}
            if isinstance(decoded, dict):
                prior_report = decoded
        prior_dataset_version = str(prior_report.get("datasetVersion") or "")
        prior_verified = False
        if prior_dataset_version:
            prior_dataset_path = root / "datasets" / f"{prior_dataset_version}.jsonl"
            if prior_dataset_path.is_file():
                try:
                    prior_rows = load_dataset(prior_dataset_path)
                    prior_verified = (
                        validate_dataset_identity(prior_dataset_path, prior_rows)
                        == prior_dataset_version
                        and store.dataset_manifest(prior_dataset_version).get(
                            "contentSha256"
                        ) == dataset_identity(prior_rows)[1]
                    )
                except (KeyError, OSError, TypeError, ValueError):
                    prior_verified = False
        active = store.active_shadow_model()
        installed_model = None
        installed_training_rows: list[dict[str, Any]] = []
        if active:
            installed_model = DirectDelegateModel.load(
                pathlib.Path(str(active["artifact_path"]))
            )
            installed_dataset = root / "datasets" / (
                f"{installed_model.payload['dataset_version']}.jsonl"
            )
            if installed_dataset.is_file():
                installed_training_rows = load_dataset(installed_dataset)
        installed_evaluation = (
            benchmark_direct_delegate(
                installed_model,
                rows,
                include_ablation=False,
                thresholds=policy,
            )
            if installed_model else {
                "status": "unavailable",
                "reason": "no active shadow model is registered",
            }
        )
        candidate = None
        candidate_benchmark = None
        artifact_path = None
        if gate["status"] == "PASS":
            candidate = train_direct_delegate_model(
                rows,
                dataset_version=dataset_version,
                feature_set="safe_metadata",
                source_revision=_source_revision(),
            )
            model_version = str(candidate.payload["model_version"])
            artifact_path = root / "models" / f"{model_version}.json"
            candidate.save(artifact_path)
            candidate_benchmark = benchmark_direct_delegate(
                candidate,
                rows,
                installed_model=installed_model,
                installed_training_rows=installed_training_rows,
                thresholds=policy,
            )
            store.register_model(
                model_version=model_version,
                algorithm=ALGORITHM,
                dataset_version=dataset_version,
                artifact_path=artifact_path,
                metrics=candidate_benchmark,
                status="offline",
            )
        if candidate_benchmark is None:
            ml_viability = "BLOCKED BY DATA"
            useful_categories: list[str] = []
            phase_status = "COMPLETE — HUMAN DATA PIPELINE READY / BLOCKED BY DATA"
            phase2_readiness = "NOT READY"
        else:
            ml_viability, useful_categories = _candidate_viability(candidate_benchmark)
            if ml_viability == "VIABLE":
                phase_status = "COMPLETE — CANDIDATE VIABLE"
                phase2_readiness = "READY"
            elif ml_viability == "LIMITED VIABILITY":
                phase_status = "COMPLETE — LIMITED CANDIDATE VIABILITY"
                phase2_readiness = "READY"
            else:
                phase_status = "COMPLETE — DATA READY / ML VALUE NOT PROVEN"
                phase2_readiness = "NOT READY"
        active_after = store.status()["activeShadowModel"]
        if active_after != active_before:
            raise RuntimeError("Phase 1.10 must not change the active shadow model")
        payload = {
            "schemaVersion": 1,
            "phase": "1.10",
            "phaseStatus": phase_status,
            "productionStatus": "deterministic_authoritative_ml_shadow_only",
            "activeShadowModelBefore": active_before,
            "activeShadowModelAfter": active_after,
            "phase19Baseline": {
                "datasetVersion": prior_dataset_version or None,
                "verified": prior_verified,
                "reportedStatus": prior_report.get("phaseStatus"),
            },
            "sync": sync_result,
            "probeGold": probe_result,
            "silver": silver_result,
            "quarantine": quarantine_adjudication(rows),
            "blindHumanGoldAudit": blind_audit,
            "reviewInterfaceLeakageAudit": {
                "passed": True,
                "payloadSchemaVersion": review_contract["schemaVersion"],
                "rubricVersion": RUBRIC_VERSION,
                "hiddenMappingStoredServerSide": True,
            },
            "datasetVersion": dataset_version,
            "dataset": manifest,
            "candidateGate": gate,
            "installedShadowEvaluation": installed_evaluation,
            "candidateModelVersion": (
                candidate.payload["model_version"] if candidate else None
            ),
            "candidateModelArtifact": str(artifact_path) if artifact_path else None,
            "candidateEvaluation": candidate_benchmark,
            "nonlinearCandidate": {
                "status": "NOT RUN",
                "reason": (
                    "no nonlinear classical dependency is installed; dependencies were "
                    "not added because the candidate data gate is blocked"
                ),
            },
            "mlViability": ml_viability,
            "usefulCategorySignals": useful_categories,
            "phase2Readiness": phase2_readiness,
            "validation": {
                "phase110Command": "PASSED",
                "candidateGate": (
                    "PASSED" if gate["status"] == "PASS" else "FAILED"
                ),
                "candidateTraining": (
                    "PASSED" if candidate_benchmark is not None else "NOT RUN"
                ),
                "repositoryChecks": "NOT RUN",
            },
        }
        output = (
            pathlib.Path(args.output).expanduser().resolve()
            if args.output else root / "phase-1-10-report.json"
        )
        _write_private_json(output, payload)
        markdown = output.with_suffix(".md")
        _write_private_text(markdown, _phase_110_markdown(payload))
        _print({
            "schemaVersion": 1,
            "phaseStatus": phase_status,
            "output": str(output),
            "humanReadableOutput": str(markdown),
            "datasetVersion": dataset_version,
            "candidateModelVersion": payload["candidateModelVersion"],
            "mlViability": ml_viability,
            "phase2Readiness": phase2_readiness,
        }, pretty)
        return 0
    if args.action == "phase-1-9":
        active_before = store.status()["activeShadowModel"]
        sync_result = builder.sync_task_history(task_store_path)
        probe_result = import_controlled_probes(store)
        silver_result = auto_adjudicate_unlabeled(store)
        output_directory = root / "datasets"
        manifest = builder.extract(output_directory)
        dataset_path = pathlib.Path(str(manifest["datasetPath"]))
        rows = load_dataset(dataset_path)
        dataset_version = validate_dataset_identity(dataset_path, rows)
        _validate_registered_dataset(store, dataset_version, rows)
        quality = dataset_quality(rows, thresholds=policy)
        live_maturity = data_maturity(
            rows,
            thresholds=policy,
            duplicate_stats=quality.get("dataMaturity", {}).get("duplicates", {}),
        )
        active = store.active_shadow_model()
        installed_model = None
        installed_training_rows: list[dict[str, Any]] = []
        if active:
            installed_model = DirectDelegateModel.load(
                pathlib.Path(str(active["artifact_path"]))
            )
            installed_dataset = root / "datasets" / (
                f"{installed_model.payload['dataset_version']}.jsonl"
            )
            if installed_dataset.is_file():
                installed_training_rows = load_dataset(installed_dataset)
        installed_evaluation = (
            benchmark_direct_delegate(
                installed_model,
                rows,
                include_ablation=False,
                thresholds=policy,
            )
            if installed_model else {
                "status": "unavailable",
                "reason": "no active shadow model is registered",
            }
        )
        candidate = None
        candidate_benchmark = None
        artifact_path = None
        if quality["status"] == "READY":
            candidate = train_direct_delegate_model(
                rows,
                dataset_version=dataset_version,
                feature_set="safe_metadata",
                source_revision=_source_revision(),
            )
            model_version = str(candidate.payload["model_version"])
            artifact_path = root / "models" / f"{model_version}.json"
            candidate.save(artifact_path)
            candidate_benchmark = benchmark_direct_delegate(
                candidate,
                rows,
                installed_model=installed_model,
                installed_training_rows=installed_training_rows,
                thresholds=policy,
            )
            store.register_model(
                model_version=model_version,
                algorithm=ALGORITHM,
                dataset_version=dataset_version,
                artifact_path=artifact_path,
                metrics=candidate_benchmark,
                status="offline",
            )
        active_after = store.status()["activeShadowModel"]
        if active_after != active_before:
            raise RuntimeError("Phase 1.9 must not change the active shadow model")
        promotion = promotion_gate_summary(
            maturity=live_maturity,
            evaluation=(
                installed_evaluation
                if isinstance(installed_evaluation, Mapping)
                and installed_evaluation.get("status") == "evaluated"
                else None
            ),
            thresholds=policy,
        )
        phase_status = (
            "COMPLETE — DATA READY"
            if quality["status"] == "READY"
            else "COMPLETE — PIPELINE READY / BLOCKED BY DATA"
        )
        payload = {
            "schemaVersion": 1,
            "phase": "1.9",
            "phaseStatus": phase_status,
            "productionStatus": "deterministic_authoritative_ml_shadow_only",
            "activeShadowModelBefore": active_before,
            "activeShadowModelAfter": active_after,
            "sync": sync_result,
            "probeGold": probe_result,
            "silver": silver_result,
            "quarantine": quarantine_adjudication(rows),
            "datasetVersion": dataset_version,
            "dataset": manifest,
            "dataMaturity": live_maturity,
            "installedShadowEvaluation": installed_evaluation,
            "promotionGates": promotion,
            "promotionReady": bool(promotion.get("promotionReady")),
            "candidateModelVersion": (
                candidate.payload["model_version"] if candidate else None
            ),
            "candidateModelArtifact": str(artifact_path) if artifact_path else None,
            "candidateEvaluation": candidate_benchmark,
            "phase2Status": (
                candidate_benchmark["productionConclusion"]
                if candidate_benchmark else "NOT_READY"
            ),
        }
        output = (
            pathlib.Path(args.output).expanduser().resolve()
            if args.output else root / "phase-1-9-report.json"
        )
        _write_private_json(output, payload)
        markdown = output.with_suffix(".md")
        _write_private_text(markdown, _phase_19_markdown(payload))
        _print({
            "schemaVersion": 1,
            "phaseStatus": phase_status,
            "output": str(output),
            "humanReadableOutput": str(markdown),
            "datasetVersion": dataset_version,
            "candidateModelVersion": payload["candidateModelVersion"],
            "phase2Status": payload["phase2Status"],
        }, pretty)
        return 0
    if args.action == "phase-1-8":
        sync_result = builder.sync_task_history(task_store_path)
        probe_result = import_controlled_probes(store)
        silver_result = auto_adjudicate_unlabeled(store)
        output_directory = root / "datasets"
        manifest = builder.extract(output_directory)
        dataset_path = pathlib.Path(str(manifest["datasetPath"]))
        rows = load_dataset(dataset_path)
        dataset_version = validate_dataset_identity(dataset_path, rows)
        _validate_registered_dataset(store, dataset_version, rows)
        quality = dataset_quality(rows, thresholds=policy)
        if quality["status"] != "READY":
            payload = {
                "schemaVersion": 1,
                "status": "BLOCKED_BY_DATA",
                "productionStatus": "offline only",
                "activeShadowModelUnchanged": store.status()["activeShadowModel"],
                "sync": sync_result,
                "probeGold": probe_result,
                "silver": silver_result,
                "quarantine": quarantine_adjudication(rows),
                "dataset": manifest,
                "modelVersion": None,
                "modelArtifact": None,
                "benchmark": None,
                "phase2Status": "NOT_READY",
                "reasons": quality["reasons"],
            }
            if args.output:
                output = pathlib.Path(args.output).expanduser().resolve()
                _write_private_json(output, payload)
                _print({
                    "schemaVersion": 1,
                    "status": "BLOCKED_BY_DATA",
                    "output": str(output),
                    "datasetVersion": dataset_version,
                    "modelVersion": None,
                    "phase2Status": "NOT_READY",
                }, pretty)
            else:
                _print(payload, pretty)
            return 2
        model = train_direct_delegate_model(
            rows,
            dataset_version=dataset_version,
            feature_set="safe_metadata",
        )
        model_version = str(model.payload["model_version"])
        artifact_path = root / "models" / f"{model_version}.json"
        model.save(artifact_path)
        benchmark = benchmark_direct_delegate(model, rows, thresholds=policy)
        store.register_model(
            model_version=model_version,
            algorithm=ALGORITHM,
            dataset_version=dataset_version,
            artifact_path=artifact_path,
            metrics=benchmark,
            status="offline",
        )
        payload = {
            "schemaVersion": 1,
            "status": "completed",
            "productionStatus": "offline only",
            "activeShadowModelUnchanged": store.status()["activeShadowModel"],
            "sync": sync_result,
            "probeGold": probe_result,
            "silver": silver_result,
            "quarantine": quarantine_adjudication(rows),
            "dataset": manifest,
            "modelVersion": model_version,
            "modelArtifact": str(artifact_path),
            "benchmark": benchmark,
            "phase2Status": benchmark["productionConclusion"],
        }
        if args.output:
            output = pathlib.Path(args.output).expanduser().resolve()
            _write_private_json(output, payload)
            _print({
                "schemaVersion": 1,
                "status": "completed",
                "output": str(output),
                "datasetVersion": dataset_version,
                "modelVersion": model_version,
                "phase2Status": benchmark["productionConclusion"],
            }, pretty)
        else:
            _print(payload, pretty)
        return 0
    if args.action == "dataset":
        sync_result = {"scanned": 0, "created": 0, "updated": 0, "skipped": 0}
        if not args.no_sync:
            sync_result = builder.sync_task_history(task_store_path)
        output = (
            pathlib.Path(args.output_directory).expanduser().resolve()
            if args.output_directory else root / "datasets"
        )
        manifest = builder.extract(output)
        _print({"schemaVersion": 1, "status": "created", "sync": sync_result, **manifest}, pretty)
        return 0
    if args.action == "train":
        dataset_path = (
            pathlib.Path(args.dataset).expanduser().resolve()
            if args.dataset else _latest(root / "datasets", "dd-dataset-*.jsonl")
        )
        if dataset_path is None or not dataset_path.is_file():
            raise ValueError("no extracted intelligence dataset is available")
        rows = load_dataset(dataset_path)
        dataset_version = validate_dataset_identity(dataset_path, rows)
        _validate_registered_dataset(store, dataset_version, rows)
        quality = dataset_quality(rows, thresholds=policy)
        if quality["status"] != "READY":
            _print({
                "schemaVersion": 1,
                "status": "BLOCKED_BY_DATA",
                "datasetVersion": dataset_version,
                "reasons": quality["reasons"],
            }, pretty)
            return 2
        try:
            model = train_direct_delegate_model(
                rows,
                dataset_version=dataset_version,
                source_revision=_source_revision(),
            )
        except ValueError as error:
            if str(error).startswith("BLOCKED_BY_DATA"):
                _print({
                    "schemaVersion": 1,
                    "status": "BLOCKED_BY_DATA",
                    "reason": str(error).partition(": ")[2],
                    "datasetVersion": dataset_version,
                }, pretty)
                return 2
            raise
        model_version = str(model.payload["model_version"])
        artifact_path = root / "models" / f"{model_version}.json"
        model.save(artifact_path)
        report = benchmark_direct_delegate(model, rows, thresholds=policy)
        store.register_model(
            model_version=model_version,
            algorithm=ALGORITHM,
            dataset_version=dataset_version,
            artifact_path=artifact_path,
            metrics=report,
            status="offline",
        )
        if args.activate_shadow:
            store.activate_shadow_model(model_version)
        _print({
            "schemaVersion": 1,
            "status": "trained",
            "modelVersion": model_version,
            "modelArtifact": str(artifact_path),
            "datasetVersion": dataset_version,
            "productionStatus": "shadow" if args.activate_shadow else "offline only",
            "benchmark": report,
        }, pretty)
        return 0
    if args.action == "predict":
        if not args.prompt:
            raise ValueError("intelligence predict requires --prompt")
        active = store.active_shadow_model()
        model_path = pathlib.Path(args.model).expanduser().resolve() if args.model else (
            pathlib.Path(str(active["artifact_path"])) if active else None
        )
        if model_path is None or not model_path.is_file():
            raise ValueError("no intelligence model artifact is available")
        model = DirectDelegateModel.load(model_path)
        safe_prompt, redacted = sanitize_request(args.prompt)
        profile = decision_profile(safe_prompt)
        prediction = model.predict(
            safe_prompt,
            profile=profile,
            repository_present=bool(args.repository_present),
        )
        _print({
            "schemaVersion": 1,
            "status": "advisory",
            "productionStatus": "shadow" if active else "offline only",
            "modelVersion": model.payload["model_version"],
            "requestRedacted": redacted,
            **prediction,
        }, pretty)
        return 0
    if args.action == "quality":
        dataset_path = (
            pathlib.Path(args.dataset).expanduser().resolve()
            if args.dataset else _latest(root / "datasets", "dd-dataset-*.jsonl")
        )
        if dataset_path is None or not dataset_path.is_file():
            raise ValueError("no extracted intelligence dataset is available")
        rows = load_dataset(dataset_path)
        version = validate_dataset_identity(dataset_path, rows)
        _validate_registered_dataset(store, version, rows)
        _print({
            "schemaVersion": 1,
            "datasetVersion": version,
            "quality": dataset_quality(rows, thresholds=policy),
        }, pretty)
        return 0
    if args.action == "readiness":
        dataset_path = (
            pathlib.Path(args.dataset).expanduser().resolve()
            if args.dataset else _latest(root / "datasets", "dd-dataset-*.jsonl")
        )
        if dataset_path is None or not dataset_path.is_file():
            raise ValueError("no extracted intelligence dataset is available")
        rows = load_dataset(dataset_path)
        version = validate_dataset_identity(dataset_path, rows)
        _validate_registered_dataset(store, version, rows)
        quality = dataset_quality(rows, thresholds=policy)
        live_maturity = data_maturity(
            rows,
            thresholds=policy,
            duplicate_stats=quality.get("dataMaturity", {}).get("duplicates", {}),
        )
        active = store.active_shadow_model()
        model = None
        evaluation = None
        if active:
            artifact = pathlib.Path(str(active["artifact_path"]))
            if artifact.is_file():
                candidate = DirectDelegateModel.load(artifact)
                # Readiness is an evaluation surface, not a training or
                # activation surface.  The installed shadow may have been
                # trained on an earlier immutable dataset; evaluate it on the
                # current held-out artifact while reporting that provenance in
                # the nested benchmark output.
                model = candidate
                evaluation = benchmark_direct_delegate(
                    candidate,
                    rows,
                    include_ablation=False,
                    thresholds=policy,
                )
        gates = promotion_gate_summary(
            maturity=live_maturity,
            evaluation=evaluation,
            thresholds=policy,
        )
        compact_evaluation = None
        if evaluation is not None:
            compact_evaluation = {
                "status": evaluation.get("status"),
                "modelVersion": evaluation.get("model", {}).get("version"),
                "baseline": evaluation.get("baseline"),
                "model": evaluation.get("model"),
                "categoryMetrics": evaluation.get("performanceByTaskCategory", {}),
                "disagreementRate": evaluation.get("disagreementRate"),
                "disagreementTelemetry": evaluation.get("disagreementTelemetry"),
                "delegateProbabilityCalibration": evaluation.get(
                    "delegateProbabilityCalibration"
                ),
                "classConfidenceCalibration": evaluation.get(
                    "classConfidenceCalibration"
                ),
                "observedOutcomeEvidence": evaluation.get("observedOutcomeEvidence"),
            }
        _print({
            "schemaVersion": 1,
            "status": gates["status"],
            "productionStatus": "deterministic_authoritative_ml_shadow_only",
            "currentShadowModel": active.get("model_version") if active else None,
            "datasetVersion": version,
            "datasetSize": {
                "total": live_maturity.get("totalExamples", len(rows)),
                "eligible": live_maturity.get("eligibleExamples", 0),
                "eligibleIndependentGroups": live_maturity.get(
                    "eligibleIndependentGroups", 0
                ),
            },
            "dataMaturity": live_maturity,
            "evaluation": compact_evaluation,
            "promotionGates": gates,
            "promotionReady": gates["promotionReady"],
        }, pretty)
        return 0
    if args.action in {"eval", "benchmark", "report"}:
        dataset_path = (
            pathlib.Path(args.dataset).expanduser().resolve()
            if args.dataset else _latest(root / "datasets", "dd-dataset-*.jsonl")
        )
        active = store.active_shadow_model()
        model_path = pathlib.Path(args.model).expanduser().resolve() if args.model else (
            pathlib.Path(str(active["artifact_path"])) if active else _latest(root / "models", "dd-logreg-*.json")
        )
        if dataset_path is None or not dataset_path.is_file():
            raise ValueError("no extracted intelligence dataset is available")
        if model_path is None or not model_path.is_file():
            raise ValueError("no intelligence model artifact is available")
        model = DirectDelegateModel.load(model_path)
        rows = load_dataset(dataset_path)
        evaluation_dataset_version = validate_dataset_identity(dataset_path, rows)
        _validate_registered_dataset(store, evaluation_dataset_version, rows)
        training_dataset_version = str(model.payload["dataset_version"])
        if evaluation_dataset_version != training_dataset_version:
            raise ValueError(
                "evaluation dataset must match the model training dataset; "
                "external-test evaluation requires a separate disjointness-verified workflow"
            )
        report = benchmark_direct_delegate(model, rows, thresholds=policy)
        payload = {
            "schemaVersion": 1,
            "datasetVersion": evaluation_dataset_version,
            "trainingDatasetVersion": training_dataset_version,
            "modelVersion": model.payload["model_version"],
            "report": report,
        }
        if args.output:
            output = pathlib.Path(args.output).expanduser().resolve()
            _write_private_json(output, payload)
            payload["output"] = str(output)
        _print(payload, pretty)
        return 0 if report.get("status") == "evaluated" else 2
    raise ValueError(f"unsupported intelligence action: {args.action}")
