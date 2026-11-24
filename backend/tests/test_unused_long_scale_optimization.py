import numpy as np
import pandas as pd

from app.detectors import IsolationForestDetector, StatisticalDetector
from app.features import FeatureConfig, TemporalFeatureBuilder


CONSUMED = [
    "value",
    "value_change",
    "robust_score",
    "dispersion",
    "gap_ratio",
    "feature_valid",
]


def _series():
    rng = np.random.default_rng(987)
    deltas = rng.choice([0.375, 3.0, 90.0], size=4999, p=[.7, .2, .1])
    seconds = np.r_[0.0, np.cumsum(deltas)]
    idx = pd.DatetimeIndex(
        pd.Timestamp("2000-01-01", tz="UTC") + pd.to_timedelta(seconds, unit="s")
    )
    return pd.Series(rng.normal(size=len(idx)), index=idx)


def test_scale1_consumed_columns_are_bitwise_identical_to_default_scale14():
    values = _series()
    common = dict(window_samples=30, min_periods=5, max_history_rows=50000, block_size=97)

    full = TemporalFeatureBuilder(90.0, FeatureConfig(scales=(1, 4), **common)).transform(values)
    lean = TemporalFeatureBuilder(90.0, FeatureConfig(scales=(1,), **common)).transform(values)

    for column in CONSUMED:
        np.testing.assert_array_equal(
            full[column].to_numpy(),
            lean[column].to_numpy(),
        )

    assert "robust_score_scale_4" in full
    assert "robust_score_scale_4" not in lean


def test_statistical_detector_output_is_identical_without_unused_scale4():
    values = _series()
    common = dict(window_samples=30, min_periods=5, max_history_rows=50000, block_size=113)
    full = TemporalFeatureBuilder(90.0, FeatureConfig(scales=(1, 4), **common)).transform(values)
    lean = TemporalFeatureBuilder(90.0, FeatureConfig(scales=(1,), **common)).transform(values)

    detector = StatisticalDetector(6.0)
    pd.testing.assert_frame_equal(detector.score(full), detector.score(lean))


def test_isolation_forest_output_is_identical_without_unused_scale4():
    values = _series()
    common = dict(window_samples=30, min_periods=5, max_history_rows=50000, block_size=101)
    full = TemporalFeatureBuilder(90.0, FeatureConfig(scales=(1, 4), **common)).transform(values)
    lean = TemporalFeatureBuilder(90.0, FeatureConfig(scales=(1,), **common)).transform(values)

    train_stop = 3500
    cols = ["value", "value_change", "robust_score", "dispersion", "gap_ratio"]

    a = IsolationForestDetector(seed=42, max_train_rows=1000, n_estimators=50, columns=cols)
    b = IsolationForestDetector(seed=42, max_train_rows=1000, n_estimators=50, columns=cols)

    a.fit(full.iloc[:train_stop])
    b.fit(lean.iloc[:train_stop])

    pd.testing.assert_frame_equal(
        a.score(full.iloc[train_stop:]),
        b.score(lean.iloc[train_stop:]),
    )
