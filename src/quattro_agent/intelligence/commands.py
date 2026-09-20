"""CLI orchestration for Quattro Intelligence Milestone 1."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
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
from .autonomous import (
    autonomous_agreement,
    autonomous_dataset_identity,
    autonomous_evidence_report,
    write_autonomous_snapshot,
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
from .evidence import evidence_acquisition_progress
from .features import REVIEW_TASK_CATEGORIES, decision_profile
from .maturity import data_maturity
from .readiness import load_promotion_thresholds, promotion_gate_summary
from .probes import import_controlled_probes
from .review import (
    BLIND_REVIEW_KIND,
    COMPLEXITY_CORRECTIONS,
    REASON_CATEGORIES,
    RUBRIC_VERSION,
    blind_review_payload,
    public_review_item,
    review_progress as blind_review_progress,
    upgrade_blind_review_payload,
    validate_blind_review_payload,
)
from .store import IntelligenceStore
from .telemetry import sanitize_request


def _latest(directory: pathlib.Path, pattern: str) -> pathlib.Path | None:
    candidates = sorted(directory.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def add_intelligence_parser(subparsers: argparse._SubParsersAction[Any]) -> None:
    """Register the intelligence command and its supported arguments."""
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
            "review", "review-priorities", "review-adjudicate", "seal-holdout",
            "blind-review-queue", "blind-review-batch", "blind-review-import",
            "blind-review-audit", "blind-review-correct",
            "generate-probes", "auto-label", "phase-1-8", "phase-1-9",
            "phase-1-10", "phase-2-2",
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
    parser.add_argument(
        "--adjudication-only",
        action="store_true",
        help="create a blind queue containing only disputed records for Reviewer C",
    )
    parser.add_argument("--vote-id")
    parser.add_argument(
        "--verdict", choices=("DIRECT", "DELEGATE", "UNCERTAIN", "REJECT")
    )
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
    """Load the promotion policy selected by the command arguments."""
    return load_promotion_thresholds(getattr(args, "thresholds", None))


def _live_maturity(
    rows: list[dict[str, Any]],
    quality: Mapping[str, Any],
    policy: Any,
) -> dict[str, Any]:
    """Add live freshness to the immutable dataset-quality gate contract."""
    policy_rows = [row for row in rows if not bool(row.get("holdout_sealed"))]
    report = data_maturity(
        policy_rows,
        thresholds=policy,
        duplicate_stats=quality.get("dataMaturity", {}).get("duplicates", {}),
    )
    report["candidateGates"] = dict(report.get("candidateGates") or {}) | dict(
        quality.get("candidateGates") or {}
    )
    return report


def _phase_19_markdown(payload: Mapping[str, Any]) -> str:
    """Render the Phase 1.9 readiness report as Markdown."""
    quality = payload.get("dataset", {}).get("quality", {})
    chronology = quality.get("chronologicalCoverage", {})
    maturity = payload.get("dataMaturity", {})
    promotion = payload.get("promotionGates", {})
    evaluation = payload.get("installedShadowEvaluation", {})
    def compact_metrics(report: Mapping[str, Any]) -> dict[str, Any]:
        """Select the headline metrics used in the Markdown report."""
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


def _installed_training_evidence(
    root: pathlib.Path,
    store: IntelligenceStore,
    model: DirectDelegateModel,
) -> list[dict[str, Any]]:
    """Load verified provenance; absence must block installed-model scoring."""
    try:
        version = model.payload["dataset_version"]
        if not isinstance(version, str) or pathlib.Path(version).name != version:
            return []
        path = root / "datasets" / f"{version}.jsonl"
        rows = load_dataset(path)
        if validate_dataset_identity(path, rows) != version:
            return []
        _validate_registered_dataset(store, version, rows)
        return rows
    except (AttributeError, OSError, KeyError, TypeError, ValueError):
        return []


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
        category = input(
            "Optional task category correction (blank to omit): "
        ).strip()
        if category and category not in REVIEW_TASK_CATEGORIES:
            print("Unknown task category; item left pending.", flush=True)
            continue
        complexity = input(
            "Optional complexity correction [low/medium/high] (blank to omit): "
        ).strip().lower()
        if complexity and complexity not in COMPLEXITY_CORRECTIONS:
            print("Unknown complexity; item left pending.", flush=True)
            continue
        item["label"] = verdict
        item["reasonCategory"] = reason or None
        item["taskCategoryCorrection"] = category or None
        item["complexityCorrection"] = complexity or None
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


def _blind_votes_from_payload(
    payload: Mapping[str, Any],
    *,
    reviewed_at: str,
) -> list[dict[str, Any]]:
    """Convert a validated reviewer artifact into store-bound vote events."""
    return [
        {
            "item_id": item["itemId"],
            "verdict": item["label"],
            "reason_category": item["reasonCategory"],
            "note": item["note"],
            "reviewed_at": reviewed_at,
            "visible_request": item["request"],
            "visible_requirements": item["requirements"],
            "task_category_correction": item.get("taskCategoryCorrection"),
            "complexity_correction": item.get("complexityCorrection"),
        }
        for item in payload["items"]
        if item.get("label") in {"DIRECT", "DELEGATE", "UNCERTAIN"}
    ]


def _evidence_progress(
    store: IntelligenceStore,
    rows: list[dict[str, Any]],
    policy: Any,
) -> dict[str, Any]:
    return evidence_acquisition_progress(
        rows,
        blind_audit=store.blind_review_audit(),
        holdout_summary=store.sealed_holdout_summary(),
        thresholds=policy,
    )


def _ordinary_evaluation_rows(
    store: IntelligenceStore,
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Exclude sealed final-holdout families from ordinary tuning reports."""
    sealed_record_ids = store.sealed_holdout_record_ids()
    sealed_groups = {
        str(row.get("group_fingerprint") or row.get("record_id"))
        for row in rows
        if str(row.get("record_id")) in sealed_record_ids
        or bool(row.get("holdout_sealed"))
    }
    return [
        row for row in rows
        if str(row.get("group_fingerprint") or row.get("record_id"))
        not in sealed_groups
    ]


def _open_ordinary_evaluation(
    store: IntelligenceStore,
    rows: list[dict[str, Any]],
    *,
    dataset_version: str,
    purpose: str,
) -> list[dict[str, Any]]:
    evaluation_rows = _ordinary_evaluation_rows(store, rows)
    store.record_evaluation_exposure(
        evaluation_rows,
        dataset_version=dataset_version,
        purpose=purpose,
    )
    return evaluation_rows


def intelligence_command(
    args: argparse.Namespace,
    *,
    state_root: pathlib.Path,
    task_store_path: pathlib.Path,
) -> int:
    """Execute an intelligence CLI action against the private state store."""
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
        current_dataset = _latest(root / "datasets", "dd-dataset-*.jsonl")
        current_rows = load_dataset(current_dataset) if current_dataset else []
        progress = _evidence_progress(store, current_rows, policy)
        candidates = store.create_blind_review_batch(
            reviewer=reviewer,
            limit=args.limit,
            acquisition_targets=progress["nextCollectionTargets"],
            adjudication_only=bool(getattr(args, "adjudication_only", False)),
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
        payload = upgrade_blind_review_payload(_read_review_file(path))
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
        payload = upgrade_blind_review_payload(
            _read_review_file(pathlib.Path(args.input).expanduser().resolve())
        )
        validate_blind_review_payload(payload)
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")
        votes = _blind_votes_from_payload(payload, reviewed_at=now)
        result = store.import_blind_review_votes(votes, reviewer=reviewer)
        _print({
            "schemaVersion": 1,
            "status": "blind_reviews_imported",
            "rubricVersion": RUBRIC_VERSION,
            **result,
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
        }, pretty)
        return 0
    if args.action == "review":
        reviewer = str(getattr(args, "reviewer", None) or "").strip()
        if not reviewer:
            raise ValueError("intelligence review requires --reviewer")
        session_id = hashlib.sha256(reviewer.encode("utf-8")).hexdigest()[:16]
        path = (
            pathlib.Path(args.input).expanduser().resolve()
            if args.input else root / "review-sessions" / f"{session_id}.json"
        )
        if path.is_file():
            payload = upgrade_blind_review_payload(_read_review_file(path))
            validate_blind_review_payload(payload)
        else:
            current_dataset = _latest(root / "datasets", "dd-dataset-*.jsonl")
            current_rows = load_dataset(current_dataset) if current_dataset else []
            progress = _evidence_progress(store, current_rows, policy)
            candidates = store.create_blind_review_batch(
                reviewer=reviewer,
                limit=args.limit,
                acquisition_targets=progress["nextCollectionTargets"],
                adjudication_only=bool(getattr(args, "adjudication_only", False)),
            )
            payload = blind_review_payload([
                public_review_item(row["item_id"], row["request_text"])
                for row in candidates
            ])
            _write_private_json(path, payload)
        review_result = _interactive_blind_review_batch(path, payload)
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")
        import_result = store.import_blind_review_votes(
            _blind_votes_from_payload(payload, reviewed_at=now), reviewer=reviewer
        )
        snapshot = None
        if import_result["imported"]:
            snapshot = builder.extract(root / "datasets")
        complete = review_result["progress"]["pending"] == 0
        if complete:
            path.unlink(missing_ok=True)
        _print({
            "schemaVersion": 1,
            "status": "review_complete" if complete else "review_paused",
            "session": str(path),
            "resumable": not complete,
            **review_result,
            "import": import_result,
            "datasetVersion": snapshot.get("datasetVersion") if snapshot else None,
        }, pretty)
        return 0
    if args.action == "review-priorities":
        dataset_path = (
            pathlib.Path(args.dataset).expanduser().resolve()
            if args.dataset else _latest(root / "datasets", "dd-dataset-*.jsonl")
        )
        if dataset_path is None or not dataset_path.is_file():
            raise ValueError("no extracted intelligence dataset is available")
        rows = load_dataset(dataset_path)
        _print({
            "schemaVersion": 1,
            "status": "prioritized",
            "reviewerPayloadBlind": True,
            "evidenceAcquisition": _evidence_progress(store, rows, policy),
        }, pretty)
        return 0
    if args.action == "review-adjudicate":
        reviewer = str(getattr(args, "reviewer", None) or "").strip()
        verdict = str(getattr(args, "verdict", None) or args.label or "")
        if not args.value or not verdict or not reviewer or not args.notes.strip():
            raise ValueError(
                "review-adjudicate requires RECORD_ID LABEL (or --verdict REJECT) "
                "--reviewer ID --notes REASON"
            )
        if verdict != "REJECT":
            raise ValueError(
                "accepted adjudication must use a third blind review; "
                "manual review-adjudicate supports --verdict REJECT only"
            )
        adjudication_id = store.adjudicate_blind_review(
            args.value,
            adjudicator=reviewer,
            verdict=verdict,
            reason=args.notes,
        )
        _print({
            "schemaVersion": 1,
            "status": "adjudicated",
            "recordId": args.value,
            "adjudicationId": adjudication_id,
        }, pretty)
        return 0
    if args.action == "seal-holdout":
        dataset_path = (
            pathlib.Path(args.dataset).expanduser().resolve()
            if args.dataset else _latest(root / "datasets", "dd-dataset-*.jsonl")
        )
        if dataset_path is None or not dataset_path.is_file():
            raise ValueError("no extracted intelligence dataset is available")
        rows = load_dataset(dataset_path)
        version = validate_dataset_identity(dataset_path, rows)
        _validate_registered_dataset(store, version, rows)
        exposed_record_ids = store.exposed_record_ids()
        exposed_groups = {
            str(row.get("group_fingerprint") or row.get("record_id"))
            for row in rows if str(row.get("record_id")) in exposed_record_ids
        }
        by_group: dict[str, dict[str, Any]] = {}
        for row in rows:
            if (
                row.get("split") != "test"
                or row.get("label_source") != "human_gold"
                or row.get("evidence_quality") not in {"consensus", "adjudicated"}
                or bool(row.get("holdout_sealed"))
            ):
                continue
            group = str(row.get("group_fingerprint") or row.get("record_id"))
            if group in exposed_groups:
                continue
            by_group.setdefault(group, row)
        balanced: dict[str, list[dict[str, Any]]] = {
            label: sorted(
                [row for row in by_group.values() if row.get("label") == label],
                key=lambda row: (
                    str(row.get("created_at") or ""), str(row.get("record_id"))
                ),
                reverse=True,
            )
            for label in ("DIRECT", "DELEGATE")
        }
        target = max(2, min(int(args.limit), 500))
        per_class = target // 2
        if any(len(balanced[label]) < per_class for label in balanced):
            raise ValueError(
                "insufficient balanced untouched human-gold test evidence to seal holdout"
            )
        members = balanced["DIRECT"][:per_class] + balanced["DELEGATE"][:per_class]
        sealed = store.seal_holdout(dataset_version=version, members=members)
        _print({
            "schemaVersion": 1,
            "status": "sealed",
            "holdoutId": sealed["holdout_id"],
            "datasetVersion": version,
            "memberCount": sealed["member_count"],
            "integritySha256": sealed["integrity_sha256"],
            "createdAt": sealed["created_at"],
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
        evaluation_rows = _open_ordinary_evaluation(
            store, rows, dataset_version=dataset_version, purpose="phase-1-10"
        )
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
            installed_training_rows = _installed_training_evidence(
                root, store, installed_model
            )
        installed_evaluation = (
            benchmark_direct_delegate(
                installed_model,
                evaluation_rows,
                include_ablation=False,
                model_training_rows=installed_training_rows,
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
                sealed_group_fingerprints=store.sealed_holdout_groups(),
            )
            model_version = str(candidate.payload["model_version"])
            artifact_path = root / "models" / f"{model_version}.json"
            candidate.save(artifact_path)
            candidate_benchmark = benchmark_direct_delegate(
                candidate,
                evaluation_rows,
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
        evaluation_rows = _open_ordinary_evaluation(
            store, rows, dataset_version=dataset_version, purpose="phase-1-9"
        )
        quality = dataset_quality(rows, thresholds=policy)
        live_maturity = _live_maturity(rows, quality, policy)
        active = store.active_shadow_model()
        installed_model = None
        installed_training_rows: list[dict[str, Any]] = []
        if active:
            installed_model = DirectDelegateModel.load(
                pathlib.Path(str(active["artifact_path"]))
            )
            installed_training_rows = _installed_training_evidence(root, store, installed_model)
        installed_evaluation = (
            benchmark_direct_delegate(
                installed_model,
                evaluation_rows,
                include_ablation=False,
                model_training_rows=installed_training_rows,
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
                sealed_group_fingerprints=store.sealed_holdout_groups(),
            )
            model_version = str(candidate.payload["model_version"])
            artifact_path = root / "models" / f"{model_version}.json"
            candidate.save(artifact_path)
            candidate_benchmark = benchmark_direct_delegate(
                candidate,
                evaluation_rows,
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
            sealed_group_fingerprints=store.sealed_holdout_groups(),
        )
        model_version = str(model.payload["model_version"])
        artifact_path = root / "models" / f"{model_version}.json"
        model.save(artifact_path)
        evaluation_rows = _open_ordinary_evaluation(
            store, rows, dataset_version=dataset_version, purpose="phase-1-8"
        )
        benchmark = benchmark_direct_delegate(
            model, evaluation_rows, thresholds=policy
        )
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
    if args.action == "phase-2-2":
        """Continuously ingest autonomous observations and train offline only."""
        sync_result = {"scanned": 0, "created": 0, "updated": 0, "skipped": 0}
        if not args.no_sync:
            sync_result = builder.sync_task_history(task_store_path)
        manifest = builder.extract(root / "datasets")
        dataset_path = pathlib.Path(str(manifest["datasetPath"]))
        rows = load_dataset(dataset_path)
        dataset_version = validate_dataset_identity(dataset_path, rows)
        _validate_registered_dataset(store, dataset_version, rows)
        autonomous_rows, autonomous_report = autonomous_evidence_report(rows)
        autonomous_version, _autonomous_digest = autonomous_dataset_identity(autonomous_rows)
        snapshot_paths = write_autonomous_snapshot(
            root / "autonomous", autonomous_version, autonomous_rows, autonomous_report
        )
        training_readiness = autonomous_report["trainingReadiness"]
        candidate = None
        candidate_report: dict[str, Any] = {
            "status": "NOT_RUN",
            "reason": "training-readiness gates are not satisfied",
            "productionAuthority": "none",
        }
        if training_readiness["status"] == "READY":
            try:
                candidate = train_direct_delegate_model(
                    autonomous_rows,
                    dataset_version=autonomous_version,
                    source_revision=_source_revision(),
                    calibrate=False,
                    allow_autonomous_sources=True,
                )
                artifact_path = root / "models" / f"{candidate.payload['model_version']}.json"
                candidate.save(artifact_path)
                agreement = autonomous_agreement(candidate, autonomous_rows)
                candidate_report = {
                    "status": "trained",
                    "modelVersion": candidate.payload["model_version"],
                    "artifactPath": str(artifact_path),
                    "datasetVersion": autonomous_version,
                    "evidenceMode": "autonomous_observation_experimental",
                    "agreement": agreement,
                    "productionAuthority": "none",
                }
                store.register_model(
                    model_version=str(candidate.payload["model_version"]),
                    algorithm=ALGORITHM,
                    dataset_version=autonomous_version,
                    artifact_path=artifact_path,
                    metrics=candidate_report,
                    status="offline",
                )
            except (OSError, TypeError, ValueError, KeyError, OverflowError) as error:
                candidate_report = {
                    "status": "failed_open",
                    "reason": str(error),
                    "productionAuthority": "none",
                }
        policy = _thresholds(args)
        evaluation_progress = _evidence_progress(store, rows, policy)
        quality = dataset_quality(rows, thresholds=policy)
        promotion = promotion_gate_summary(
            maturity=quality.get("dataMaturity", {}),
            evaluation=None,
            thresholds=policy,
        )
        evaluation_readiness = {
            "status": "READY" if all((
                evaluation_progress["humanGold"]["current"] >= policy.minimum_human_gold_groups,
                evaluation_progress["chronology"]["usable"],
                quality.get("candidateGates", {}).get("zeroCrossSplitContamination") is True,
            )) else "BLOCKED_BY_DATA",
            "gates": {
                "protectedHumanGold": evaluation_progress["humanGold"]["current"] >= policy.minimum_human_gold_groups,
                "credibleChronology": bool(evaluation_progress["chronology"]["usable"]),
                "zeroCrossSplitContamination": quality.get("candidateGates", {}).get(
                    "zeroCrossSplitContamination"
                ),
            },
            "evidence": {
                "acceptedHumanGold": evaluation_progress["humanGold"],
                "chronology": evaluation_progress["chronology"],
            },
        }
        phase_status = (
            "PHASE 2.2 COMPLETE — AUTONOMOUS EVIDENCE ACTIVE — "
            "EXPERIMENTAL TRAINING READY — PRODUCTION PROMOTION STILL BLOCKED"
            if candidate_report["status"] == "trained"
            else "PHASE 2.2 ACTIVE — AUTONOMOUS EVIDENCE INGESTED — TRAINING BLOCKED"
        )
        payload = {
            "schemaVersion": 1,
            "phase": "2.2",
            "phaseStatus": phase_status,
            "sync": sync_result,
            "datasetVersion": dataset_version,
            "datasetPath": str(dataset_path),
            "autonomousEvidence": autonomous_report | snapshot_paths,
            "trainingReadiness": training_readiness,
            "experimentalCandidate": candidate_report,
            "evaluationReadiness": evaluation_readiness,
            "productionPromotionReadiness": promotion,
            "productionStatus": "deterministic_authoritative_ml_shadow_only",
        }
        output = (
            pathlib.Path(args.output).expanduser().resolve()
            if args.output else root / "reports" / "phase-2-2-report.json"
        )
        _write_private_json(output, payload)
        _print({
            "schemaVersion": 1,
            "phaseStatus": phase_status,
            "output": str(output),
            "datasetVersion": dataset_version,
            "autonomousDatasetVersion": autonomous_version,
            "trainingReadiness": training_readiness["status"],
            "candidateStatus": candidate_report["status"],
            "evaluationReadiness": evaluation_readiness["status"],
            "productionPromotionReadiness": promotion["status"],
        }, pretty)
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
                sealed_group_fingerprints=store.sealed_holdout_groups(),
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
        evaluation_rows = _open_ordinary_evaluation(
            store, rows, dataset_version=dataset_version, purpose="train-benchmark"
        )
        report = benchmark_direct_delegate(model, evaluation_rows, thresholds=policy)
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
        analysis_rows = _ordinary_evaluation_rows(store, rows)
        quality = dataset_quality(analysis_rows, thresholds=policy)
        live_maturity = _live_maturity(analysis_rows, quality, policy)
        active = store.active_shadow_model()
        evaluation = None
        if active:
            try:
                model = DirectDelegateModel.load(pathlib.Path(str(active["artifact_path"])))
            except (AttributeError, OSError, KeyError, TypeError, ValueError):
                evaluation = {
                    "status": "unavailable",
                    "reason": "active shadow model artifact could not be loaded",
                }
            else:
                # Evaluate only on evidence disjoint from the installed artifact,
                # not merely on rows held out by the newest dataset extraction.
                evaluation_rows = _open_ordinary_evaluation(
                    store, rows, dataset_version=version, purpose="readiness"
                )
                evaluation = benchmark_direct_delegate(
                    model,
                    evaluation_rows,
                    include_ablation=False,
                    model_training_rows=_installed_training_evidence(root, store, model),
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
                "reason": evaluation.get("reason"),
                "holdoutEvidence": evaluation.get("holdoutEvidence"),
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
        evidence_progress = _evidence_progress(store, analysis_rows, policy)
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
            "evidenceAcquisition": evidence_progress,
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
        evaluation_rows = _open_ordinary_evaluation(
            store,
            rows,
            dataset_version=evaluation_dataset_version,
            purpose=args.action,
        )
        report = benchmark_direct_delegate(model, evaluation_rows, thresholds=policy)
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
