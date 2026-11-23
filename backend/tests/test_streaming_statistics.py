"""Exact parity and bounded external-sort behavior for the frozen fitter."""
import numpy as np
import pandas as pd
import pytest

from app.calibration import QuantileCalibrator
from app.streaming_statistics import ExternalOrderStatistics, calibrate_stream, fit_temporal_stream
from app.temporal import TemporalDetector


def series(values):
    return pd.Series(values, index=pd.date_range("2001-01-01", periods=len(values), freq="3s", tz="UTC"))


def factory(raw, batch):
    return lambda: (raw.iloc[start:start + batch] for start in range(0, len(raw), batch))


@pytest.mark.parametrize("batch", [1, 7, 64, 5000])
@pytest.mark.parametrize("kind", ["odd", "even", "constant", "quantized", "missing", "overflow"])
def test_temporal_training_exact_parity(tmp_path, batch, kind):
    rng = np.random.default_rng(873)
    values = rng.normal(size=201 if kind == "odd" else 200)
    if kind == "constant":
        values[:] = 1.25
    elif kind == "quantized":
        values = np.round(values, 1).astype(np.float32)
    elif kind == "missing":
        values[[6, 7, 30, 80, 199]] = [np.nan, np.inf, -np.inf, np.nan, np.nan]
    elif kind == "overflow":
        values = np.tile([1e308, -1e308, np.nan, 0., 0.], 40)
    raw = series(values)
    with np.errstate(over="ignore", invalid="ignore"):
        expected = TemporalDetector().fit(raw)
        actual = fit_temporal_stream(factory(raw, batch), tmp_path, run_rows=31, fan_in=3, buffer_rows=5)
    assert actual.metadata() == expected.metadata()
    for name in ("location", "floor", "global_scale", "change_scale"):
        assert getattr(actual, name) == getattr(expected, name)
    assert actual._history is None and actual._last is None
    assert not list(tmp_path.iterdir())
    for key in ("value_sort", "step_sort", "deviation_sort"):
        metrics = actual.streaming_resources[key]
        assert metrics["max_run_rows"] <= 31
        assert metrics["max_merge_input_runs"] <= 3
        assert metrics["max_merge_buffer_values"] <= 2 * 3 * 5


@pytest.mark.parametrize("batch", [1, 9, 1000])
@pytest.mark.parametrize("floor", [0, 3, 200])
def test_calibration_higher_ties_finite_filter_and_exceedance(tmp_path, batch, floor):
    raw = series(np.r_[np.arange(99), [98., 99., 99., np.nan, np.inf, -np.inf]])
    expected = QuantileCalibrator(.01, floor).fit(raw)
    actual = calibrate_stream(factory(raw, batch), tmp_path, minimum_threshold=floor,
                              run_rows=13, fan_in=3, buffer_rows=4)
    assert actual.metadata() == expected.metadata()
    assert actual.threshold == expected.threshold
    assert not list(tmp_path.iterdir())


def test_sorter_exact_order_statistics_and_bounded_multi_pass_merge(tmp_path):
    values = np.random.default_rng(92).normal(size=12001)
    values[20:40] = 0.
    with ExternalOrderStatistics(tmp_path, run_rows=43, fan_in=4, buffer_rows=7) as sorter:
        sorter.add(values)
        assert sorter.median() == float(np.median(values))
        for q in (0., .1, .5, .99, 1.):
            assert sorter.quantile_higher(q) == float(np.quantile(values, q, method="higher"))
        assert sorter.count_above(.1) == int(np.count_nonzero(values > .1))
        assert np.array_equal(np.concatenate(list(sorter.iter_values())), np.sort(values))
        metrics = sorter.metrics()
        assert metrics["merge_operations"] > 4
        assert metrics["max_merge_input_runs"] <= 4
        assert metrics["max_merge_buffer_values"] <= 56
        assert metrics["max_live_run_metadata"] < 20
        assert metrics["temporary_peak_bytes"] <= 3 * len(values) * 8
    assert not list(tmp_path.iterdir())


def test_missing_boundary_does_not_create_training_step(tmp_path):
    raw = series(np.r_[np.zeros(31), np.nan, np.full(31, 100.)])
    actual = fit_temporal_stream(factory(raw, 32), tmp_path, run_rows=32, fan_in=2, buffer_rows=8)
    assert actual.training["median_positive_training_step"] == 0
    assert actual.metadata() == TemporalDetector().fit(raw).metadata()


@pytest.mark.parametrize("fit", [fit_temporal_stream, calibrate_stream])
def test_boundaries_and_chronological_batches_rejected(tmp_path, fit):
    raw = series(np.arange(100.))
    boundary = {"train_end" if fit is fit_temporal_stream else "validation_end": raw.index[-2]}
    with pytest.raises(ValueError, match="boundary"):
        fit(factory(raw, 20), tmp_path, **boundary)
    with pytest.raises(ValueError, match="chronological"):
        fit(lambda: iter([raw.iloc[:50], raw.iloc[40:]]), tmp_path)
    assert not list(tmp_path.iterdir())


def test_empty_or_nonfinite_training_and_validation_rejected(tmp_path):
    with pytest.raises(ValueError, match="thirty"):
        fit_temporal_stream(factory(series(np.arange(29.)), 5), tmp_path)
    with pytest.raises(ValueError, match="finite validation"):
        calibrate_stream(factory(series([np.nan, np.inf, -np.inf]), 1), tmp_path)
    with pytest.raises(ValueError, match="nonempty"):
        calibrate_stream(lambda: iter([]), tmp_path)


def test_scratch_cleanup_preserves_unrelated_files(tmp_path):
    preserved = tmp_path / "prior_result.json"
    preserved.write_text("untouched")
    with pytest.raises(RuntimeError, match="injected"):
        with ExternalOrderStatistics(tmp_path, run_rows=4) as sorter:
            sorter.add(np.arange(10.))
            raise RuntimeError("injected")
    assert list(tmp_path.iterdir()) == [preserved]
    assert preserved.read_text() == "untouched"


def test_long_generated_stream_without_full_array_keeps_buffers_bounded(tmp_path):
    rows = 200_000
    with ExternalOrderStatistics(tmp_path, run_rows=2048, fan_in=4, buffer_rows=256) as sorter:
        for start in range(0, rows, 1000):
            sorter.add(np.arange(start, min(start + 1000, rows), dtype=np.float64))
        assert sorter.median() == (rows - 1) / 2
        assert sorter.quantile_higher(.99) == float(np.ceil((rows - 1) * .99))
        metrics = sorter.metrics()
        assert metrics["max_run_rows"] <= 2048
        assert metrics["max_merge_buffer_values"] <= 2 * 4 * 256
        assert metrics["max_live_run_metadata"] < 25
        assert metrics["temporary_peak_bytes"] <= 3 * rows * 8


def test_even_median_preserves_float64_overflow_semantics(tmp_path):
    raw = series(np.full(40, 1e308))
    with np.errstate(over="ignore", invalid="ignore"):
        expected = TemporalDetector().fit(raw)
        actual = fit_temporal_stream(factory(raw, 7), tmp_path, run_rows=11, fan_in=3, buffer_rows=5)
    assert np.isposinf(expected.location)
    assert actual.metadata() == expected.metadata()
