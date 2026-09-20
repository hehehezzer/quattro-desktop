"""Quattro Intelligence telemetry, datasets, evaluation, and shadow routing."""

from .classical import DirectDelegateModel, train_direct_delegate_model
from .dataset import DatasetBuilder
from .evaluation import benchmark_direct_delegate
from .maturity import data_maturity
from .readiness import PromotionThresholds, promotion_gate_summary
from .store import IntelligenceStore
from .telemetry import record_routing_telemetry, update_execution_telemetry

__all__ = [
    "DatasetBuilder",
    "DirectDelegateModel",
    "IntelligenceStore",
    "benchmark_direct_delegate",
    "data_maturity",
    "PromotionThresholds",
    "promotion_gate_summary",
    "record_routing_telemetry",
    "train_direct_delegate_model",
    "update_execution_telemetry",
]
