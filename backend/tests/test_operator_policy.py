import numpy as np
import pytest

from app.operator_policy import (
    m13_baseline_flags,
    operator_policy_metadata,
    temporal_first_operator_flags,
)


def test_temporal_first_operator_flags_are_exact_copy():
    temporal = np.array([True, False, True, False], dtype=bool)
    actual = temporal_first_operator_flags(temporal)
    np.testing.assert_array_equal(actual, temporal)
    assert actual is not temporal


def test_isolation_forest_cannot_create_active_operator_incident():
    temporal = np.array([False, False, True, False], dtype=bool)
    isolation = np.array([True, True, True, True], dtype=bool)
    ratio = np.array([0.75, 1.25, 0.1, np.nan], dtype=float)

    active = temporal_first_operator_flags(temporal)
    baseline = m13_baseline_flags(temporal, isolation, ratio)

    np.testing.assert_array_equal(active, [False, False, True, False])
    np.testing.assert_array_equal(baseline, [True, True, True, False])


def test_baseline_rule_rejects_nonfinite_ratio_for_if_only_path():
    temporal = np.array([False, False, True], dtype=bool)
    isolation = np.array([True, True, True], dtype=bool)
    ratio = np.array([np.nan, np.inf, np.nan], dtype=float)
    np.testing.assert_array_equal(
        m13_baseline_flags(temporal, isolation, ratio),
        [False, False, True],
    )


@pytest.mark.parametrize(
    "temporal,isolation,ratio",
    [
        ([[True]], [True], [1.0]),
        ([True, False], [True], [1.0]),
        ([True], [True], [1.0, 2.0]),
    ],
)
def test_baseline_rejects_bad_shapes(temporal, isolation, ratio):
    with pytest.raises(ValueError):
        m13_baseline_flags(temporal, isolation, ratio)


def test_metadata_discloses_scientific_boundary():
    meta = operator_policy_metadata()
    assert meta["version"] == "m1.3.1-temporal-first"
    assert "Run #10 B" in meta["selection_basis"]
    assert "fresh predeclared B1" in meta["validation_status"]
