import numpy as np
import pandas as pd
import pytest

from app.features import FeatureConfig, TemporalFeatureBuilder


def series(values, frequency="30s"):
    return pd.Series(values, index=pd.date_range("2000-01-01", periods=len(values), freq=frequency, tz="UTC"))


@pytest.mark.parametrize("frequency,cadence", [("3s", 3), ("30s", 30), ("90s", 90), ("15min", 900)])
def test_cadence_derived_windows(frequency, cadence):
    values = series(np.arange(20), frequency)
    builder = TemporalFeatureBuilder(cadence, FeatureConfig(window_samples=5, min_periods=3))
    result = builder.transform(values)
    assert result.rolling_median.iloc[10] == 7
    assert result.gap_seconds.iloc[1] == cadence
    assert builder.metadata()["windows_seconds"]["1"] == cadence * 5


def test_exact_history_mad_and_no_current_value_in_baseline():
    values = series([1, 2, 3, 100, 1000])
    result = TemporalFeatureBuilder(30, FeatureConfig(window_samples=4, min_periods=3)).transform(values)
    # History at t=4 is [1,2,3,100], median 2.5, absolute deviations 1.5,.5,.5,97.5.
    assert result.rolling_median.iloc[4] == 2.5
    assert result.rolling_mad.iloc[4] == 1.0


def test_future_observations_cannot_change_past_features():
    values = series(np.linspace(0, 20, 200))
    changed = values.copy()
    changed.iloc[120:] = 1e9
    left = TemporalFeatureBuilder(30).transform(values)
    right = TemporalFeatureBuilder(30).transform(changed)
    pd.testing.assert_frame_equal(left.iloc[:120], right.iloc[:120])


def test_chunked_features_equal_single_batch_with_irregular_gaps():
    rng = np.random.default_rng(2)
    times = pd.Timestamp("2000-01-01", tz="UTC") + pd.to_timedelta(np.cumsum(rng.choice([3, 6, 30], 230)), unit="s")
    values = pd.Series(rng.normal(size=len(times)), index=times)
    values.iloc[50:55] = np.nan
    expected = TemporalFeatureBuilder(3).transform(values)
    builder = TemporalFeatureBuilder(3)
    actual = pd.concat([builder.transform(values.iloc[:50]), builder.transform(values.iloc[50:103]), builder.transform(values.iloc[103:])])
    pd.testing.assert_frame_equal(actual, expected)
    assert actual.gap_ratio.max() == 10


def test_constant_zero_mad_and_spike_still_detected():
    values = series(np.r_[np.ones(80), 10, np.ones(10)])
    result = TemporalFeatureBuilder(30).transform(values)
    assert np.isfinite(result.robust_score).all()
    assert (result.robust_score.iloc[:80] == 0).all()
    assert result.robust_score.iloc[80] > 6
    assert result.rolling_mad.iloc[80] == 0


def test_missing_values_are_not_timestamp_gaps_and_zero_relative_is_unknown():
    result = TemporalFeatureBuilder(30).transform(series([0, 1, np.nan, 1, 2, 3, 4, 5]))
    assert result.relative_change.iloc[1] != result.relative_change.iloc[1]
    assert result.missing_value.iloc[2] == 1
    assert result.gap_ratio.iloc[2] == 1
    assert result.robust_score.iloc[2] == 0


def test_time_window_excludes_old_observations_after_gap():
    values = series(np.arange(8))
    values.index = values.index[:7].append(pd.DatetimeIndex([values.index[-1] + pd.Timedelta("2h")]))
    result = TemporalFeatureBuilder(30, FeatureConfig(window_samples=5, min_periods=3)).transform(values)
    assert np.isnan(result.rolling_median.iloc[-1])
    assert result.history_count.iloc[-1] == 0


def test_history_cap_and_invalid_time_order_fail_explicitly():
    builder = TemporalFeatureBuilder(30, FeatureConfig(max_history_rows=10))
    with pytest.raises(ValueError, match="max_history_rows"):
        builder.transform(series(np.ones(50), "1s"))
    with pytest.raises(ValueError, match="strictly increasing"):
        TemporalFeatureBuilder(30).transform(series([1, 2, 3]).iloc[::-1])
    builder = TemporalFeatureBuilder(30)
    values = series(np.ones(20))
    builder.transform(values)
    with pytest.raises(ValueError, match="non-overlapping"):
        builder.transform(values)
