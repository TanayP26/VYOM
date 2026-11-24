"""Versioned operator-facing incident policies.

M1.3.1 makes the calibrated temporal detector the sole creator of operator
incidents. Isolation Forest remains an independent comparator and cannot create
an operator incident by itself.
"""
from __future__ import annotations

import numpy as np

POLICY_VERSION = "m1.3.1-temporal-first"
M13_BASELINE_RATIO = 0.5
FULL_THRESHOLD_RATIO = 1.0


def build_combined_policy_candidates(temporal_flag, isolation_forest_flag, temporal_ratio):
    """Return the active policy and two explicitly named comparison policies.

    The active combined policy is temporal-first. The M1.3.0 rule and the
    full-calibrated-threshold challenger are retained for audit/comparison only.
    A non-finite temporal ratio can never corroborate an Isolation Forest flag.
    """
    temporal = np.asarray(temporal_flag, dtype=bool)
    isolation = np.asarray(isolation_forest_flag, dtype=bool)
    ratio = np.asarray(temporal_ratio, dtype=float)

    if temporal.ndim != 1 or isolation.ndim != 1 or ratio.ndim != 1:
        raise ValueError("Policy inputs must be one-dimensional arrays")
    if temporal.shape != isolation.shape or temporal.shape != ratio.shape:
        raise ValueError("Policy inputs must have identical shapes")

    finite = np.isfinite(ratio)
    baseline = temporal | (isolation & finite & (ratio > M13_BASELINE_RATIO))
    full_threshold = temporal | (isolation & finite & (ratio > FULL_THRESHOLD_RATIO))

    return {
        "combined": temporal.copy(),
        "combined_m13_baseline": baseline,
        "combined_if_full_threshold": full_threshold,
    }


def operator_policy_metadata():
    """Machine-readable policy provenance embedded in every new run."""
    return {
        "version": POLICY_VERSION,
        "active_model": "combined",
        "active_rule": "temporal_point_flag OR persistent_temporal_interval_flag",
        "isolation_forest_role": (
            "independent comparator/supporting evidence; it cannot create an "
            "operator-facing incident in the active policy"
        ),
        "preserved_baseline": {
            "model": "combined_m13_baseline",
            "rule": "temporal_flag OR (isolation_forest_flag AND temporal_ratio > 0.5)",
            "active": False,
        },
        "research_challenger": {
            "model": "combined_if_full_threshold",
            "rule": "temporal_flag OR (isolation_forest_flag AND temporal_ratio > 1.0)",
            "active": False,
            "rationale": "requires temporal score to exceed its calibrated threshold",
        },
        "selection_basis": (
            "Development-exposed A diagnostics: temporal candidates retained the "
            "supported channel_12 interval and channel_61 point detections; adding "
            "Isolation Forest increased alert burden in the channel_74 diagnostic "
            "without establishing a general benefit."
        ),
        "test_partition_use": (
            "Run #10 B was used only to diagnose the M1.3.0 mechanism, not to select "
            "the active policy or tune a threshold."
        ),
        "validation_status": (
            "Research policy requiring a fresh, predeclared B1 evaluation; not "
            "external blind validation or flight-qualified."
        ),
    }
