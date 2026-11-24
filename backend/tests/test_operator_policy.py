import numpy as np
import pytest

from app.operator_policy import (
    build_combined_policy_candidates,
    operator_policy_metadata,
)


def test_active_operator_policy_is_temporal_first_and_if_cannot_create_incidents():
    temporal = np.array([True, False, False, True, False])
    isolation = np.array([False, True, True, True, True])
    ratio = np.array([0.2, 0.75, 1.2, 0.4, np.nan])

    result = build_combined_policy_candidates(temporal, isolation, ratio)

    np.testing.assert_array_equal(result["combined"], temporal)
    np.testing.assert_array_equal(
        result["combined_m13_baseline"],
        np.array([True, True, True, True, False]),
    )
    np.testing.assert_array_equal(
        result["combined_if_full_threshold"],
        np.array([True, False, True, True, False]),
    )


def test_nonfinite_temporal_ratio_never_corroborates_isolation_forest():
    result = build_combined_policy_candidates(
        [False, False, True],
        [True, True, True],
        [np.nan, np.inf, np.nan],
    )
    np.testing.assert_array_equal(result["combined"], [False, False, True])
    np.testing.assert_array_equal(result["combined_m13_baseline"], [False, False, True])
    np.testing.assert_array_equal(result["combined_if_full_threshold"], [False, False, True])


@pytest.mark.parametrize(
    "temporal,isolation,ratio",
    [
        ([[True]], [True], [1.2]),
        ([True, False], [True], [1.2]),
        ([True], [True], [1.2, 0.8]),
    ],
)
def test_policy_rejects_non_1d_or_misaligned_inputs(temporal, isolation, ratio):
    with pytest.raises(ValueError):
        build_combined_policy_candidates(temporal, isolation, ratio)


def test_policy_metadata_preserves_baseline_and_discloses_validation_boundary():
    metadata = operator_policy_metadata()
    assert metadata["version"] == "m1.3.1-temporal-first"
    assert metadata["active_rule"] == "temporal_point_flag OR persistent_temporal_interval_flag"
    assert metadata["preserved_baseline"]["active"] is False
    assert metadata["research_challenger"]["active"] is False
    assert "Run #10 B" in metadata["test_partition_use"]
    assert "not external blind validation" in metadata["validation_status"]
