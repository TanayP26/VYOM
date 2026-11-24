import warnings
import numpy as np
import pandas as pd

from app.features import FeatureConfig, TemporalFeatureBuilder


def _old_statistics(values, times, duration, offset, config):
    starts = np.searchsorted(times, times[offset:] - duration, side="left")
    ends = np.arange(offset, len(values))
    widths = ends - starts
    result = [np.full(len(ends), np.nan) for _ in range(4)]
    counts = np.zeros(len(ends), dtype=np.int32)

    for lo in range(0, len(ends), config.block_size):
        hi = min(lo + config.block_size, len(ends))
        width = int(widths[lo:hi].max(initial=0))
        if width == 0:
            continue
        positions = ends[lo:hi, None] - np.arange(1, width + 1)[None, :]
        valid = positions >= starts[lo:hi, None]
        window = values[np.maximum(positions, 0)].copy()
        window[~valid] = np.nan
        count = np.sum(np.isfinite(window), axis=1)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            median = np.nanmedian(window, axis=1)
            mad = np.nanmedian(np.abs(window - median[:, None]), axis=1)
            quartiles = np.nanquantile(window, [.25, .75], axis=1)
        too_short = count < config.min_periods
        for destination, column in zip(result, (median, mad, quartiles[0], quartiles[1])):
            column[too_short] = np.nan
            destination[lo:hi] = column
        counts[lo:hi] = count
    return *result, counts


def test_optimized_kernel_is_exactly_equal_to_frozen_kernel():
    rng = np.random.default_rng(123)
    n = 1500
    deltas = rng.choice([0.375, 1.0, 3.0, 90.0], size=n - 1, p=[.55, .2, .15, .1])
    ns = np.r_[0.0, np.cumsum(deltas)]
    index = pd.DatetimeIndex(
        pd.Timestamp("2000-01-01", tz="UTC") + pd.to_timedelta(ns, unit="s")
    )
    values = rng.normal(size=n).astype(float)
    values[::97] = np.nan

    cfg = FeatureConfig(
        window_samples=30,
        scales=(1, 4),
        min_periods=5,
        max_history_rows=50000,
        block_size=73,
    )
    builder = TemporalFeatureBuilder(90.0, cfg)

    normalized = pd.Series(values, index=index).astype(np.float64).replace(
        [np.inf, -np.inf], np.nan
    )
    times = index.as_unit("ns").asi8
    array = normalized.to_numpy()

    for scale in cfg.scales:
        duration = int(round(90.0 * cfg.window_samples * scale * 1e9))
        expected = _old_statistics(array, times, duration, 0, cfg)
        actual = builder._statistics(array.copy(), times.copy(), duration, 0)

        for old, new in zip(expected[:-1], actual[:-1]):
            np.testing.assert_array_equal(np.isnan(new), np.isnan(old))
            np.testing.assert_allclose(new, old, rtol=0.0, atol=0.0, equal_nan=True)
        np.testing.assert_array_equal(actual[-1], expected[-1])


def test_full_feature_frame_remains_batch_invariant_after_kernel_optimization():
    rng = np.random.default_rng(456)
    idx = pd.date_range("2000-01-01", periods=1800, freq="3s", tz="UTC")
    values = pd.Series(rng.normal(size=len(idx)), index=idx)

    cfg = FeatureConfig(
        window_samples=30,
        scales=(1, 4),
        min_periods=5,
        max_history_rows=50000,
        block_size=64,
    )

    expected = TemporalFeatureBuilder(3.0, cfg).transform(values)

    builder = TemporalFeatureBuilder(3.0, cfg)
    actual = pd.concat([
        builder.transform(values.iloc[:317]),
        builder.transform(values.iloc[317:911]),
        builder.transform(values.iloc[911:]),
    ])

    pd.testing.assert_frame_equal(actual, expected)
