"""Versioned operator-facing incident policy for VYOM M1.3.1.

The active operator stream is temporal-first. Isolation Forest remains a
separately reported comparator and cannot create an operator incident by itself.
"""
from __future__ import annotations

import numpy as np

POLICY_VERSION = "m1.3.1-temporal-first"


def temporal_first_operator_flags(temporal_flag):
    flags = np.asarray(temporal_flag, dtype=bool)
    if flags.ndim != 1:
        raise ValueError("temporal_flag must be one-dimensional")
    return flags.copy()


def m13_baseline_flags(temporal_flag, isolation_forest_flag, temporal_ratio):
    """Exact M1.3.0 half-threshold rule, retained for diagnostics only."""
    temporal = np.asarray(temporal_flag, dtype=bool)
    isolation = np.asarray(isolation_forest_flag, dtype=bool)
    ratio = np.asarray(temporal_ratio, dtype=float)
    if temporal.ndim != 1 or isolation.ndim != 1 or ratio.ndim != 1:
        raise ValueError("policy inputs must be one-dimensional")
    if temporal.shape != isolation.shape or temporal.shape != ratio.shape:
        raise ValueError("policy inputs must have identical shapes")
    return temporal | (isolation & np.isfinite(ratio) & (ratio > 0.5))


def operator_policy_metadata():
    return {
        "version": POLICY_VERSION,
        "active_model": "combined",
        "active_rule": "temporal_point_flag OR persistent_temporal_interval_flag",
        "isolation_forest_role": (
            "independent comparator/supporting evidence; cannot create an "
            "operator-facing incident"
        ),
        "m13_baseline_rule": (
            "temporal_flag OR "
            "(isolation_forest_flag AND temporal_ratio > 0.5)"
        ),
        "selection_basis": (
            "Development-exposed A diagnostics supported temporal-first use; "
            "Run #10 B was used only to diagnose the old half-threshold mechanism."
        ),
        "validation_status": (
            "Requires a fresh predeclared B1 Target=YES evaluation; "
            "not external blind validation or flight-qualified."
        ),
    }
