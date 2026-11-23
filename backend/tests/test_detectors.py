import numpy as np
import pandas as pd
import pytest

from app.detectors import (BoundedTrainingSampler, IsolationForestDetector, PCAReconstructionDetector,
                           StatisticalDetector, align_channels, fit_random_forest)
from app.features import TemporalFeatureBuilder


def features(rows=500):
    values = pd.Series(np.random.default_rng(9).normal(size=rows),
                       index=pd.date_range("2000-01-01", periods=rows, freq="30s", tz="UTC"))
    return TemporalFeatureBuilder(30).transform(values)


def test_sampling_is_bounded_deterministic_and_batch_invariant():
    frame = features()
    one = BoundedTrainingSampler(50, seed=3)
    one.update(frame)
    many = BoundedTrainingSampler(50, seed=3)
    for offset in range(0, len(frame), 33):
        many.update(frame.iloc[offset:offset + 33])
    pd.testing.assert_frame_equal(one.sample(), many.sample())
    assert many.metadata()["training_sample_rows"] == 50
    assert many.metadata()["training_rows_seen"] == 500


def test_training_boundary_is_enforced():
    frame = features()
    with pytest.raises(ValueError, match="training boundary"):
        IsolationForestDetector().fit(frame, train_end=frame.index[200])
    with pytest.raises(ValueError, match="training boundary"):
        StatisticalDetector(quantile=.99).fit(frame, train_end=frame.index[200])


def test_statistical_threshold_calibrated_training_only_and_strict():
    frame = features()
    detector = StatisticalDetector(quantile=.9).fit(frame.iloc[:300])
    threshold = detector.threshold
    test = frame.iloc[300:].copy()
    test["robust_score"] = 1e6
    assert detector.score(test).statistical_flag.all()
    assert detector.threshold == threshold
    constant = frame.iloc[300:].copy()
    constant["robust_score"] = 0
    assert not StatisticalDetector(threshold=0).score(constant).statistical_flag.any()


def test_iforest_training_only_reproducible_batched_and_persisted(tmp_path):
    frame = features()
    train = frame.iloc[:300]
    one = IsolationForestDetector(seed=7, max_train_rows=100, batch_size=31, n_estimators=20).fit(train, train_end=train.index[-1])
    two = IsolationForestDetector(seed=7, max_train_rows=100, batch_size=1000, n_estimators=20).fit([train.iloc[:99], train.iloc[99:]])
    scores = one.score(frame.iloc[300:])
    pd.testing.assert_frame_equal(scores, two.score(frame.iloc[300:]))
    assert np.isfinite(scores.iforest_score).all()
    assert one.metadata()["training_sample_rows"] == 100
    medians = one.fill_values.copy()
    extreme = frame.iloc[300:].copy() * 1e4
    one.score(extreme)
    pd.testing.assert_series_equal(medians, one.fill_values)
    path = one.save(tmp_path / "iforest.joblib")
    pd.testing.assert_frame_equal(scores, IsolationForestDetector.load(path).score(frame.iloc[300:]))


def test_iforest_missing_and_constant_data_safe():
    frame = features()
    frame.loc[:, ["value", "value_change", "robust_score", "dispersion"]] = 0
    model = IsolationForestDetector(n_estimators=10).fit(frame)
    assert not model.score(frame).iforest_flag.any()
    frame.loc[frame.index[-1], "value"] = np.nan
    assert not model.score(frame).iforest_flag.iloc[-1]


def test_pca_alignment_explicit_units_right_edge_and_train_only():
    index = pd.date_range("2000-01-01", periods=200, freq="30s", tz="UTC")
    a = pd.Series(np.sin(np.arange(200) / 20), index=index)
    b = pd.Series(np.sin(np.arange(200) / 20) * 2, index=index)
    with pytest.raises(ValueError, match="Mixed physical units"):
        align_channels({"a": a, "b": b}, "1min", {"a": "V", "b": "A"})
    aligned, report = align_channels({"a": a, "b": b}, "1min", {"a": "V", "b": "A"}, allow_mixed_units=True)
    assert aligned.index[0] == index[0] + pd.Timedelta("1min")
    assert aligned.a.iloc[0] == pytest.approx(a.iloc[:2].mean())
    model = PCAReconstructionDetector().fit(aligned.iloc[:70], alignment=report, train_end=aligned.index[69])
    threshold = model.threshold
    test = aligned.iloc[70:].copy()
    test["b"] += 100
    assert model.score(test).pca_flag.all()
    assert model.threshold == threshold
    assert model.metadata()["alignment"]["mixed_units"] is True


def test_pca_resample_grid_is_bounded_before_allocation():
    index = pd.to_datetime(["2000-01-01", "2020-01-01"], utc=True)
    a = pd.Series([1, 2], index=index)
    with pytest.raises(ValueError, match="grid exceeds"):
        align_channels({"a": a, "b": a}, "1s", {"a": "V", "b": "V"}, max_rows=1000)


def test_supervised_unknown_policy_and_unlabelled_channels():
    frame = features(200)[["value", "robust_score"]].fillna(0)
    labels = pd.Series(np.nan, index=frame.index)
    labels.iloc[50:80] = 1
    model, info = fit_random_forest(frame, labels)
    assert model is None and info["status"] == "skipped"
    model, info = fit_random_forest(frame, labels, unlabelled_policy="assume_normal")
    assert model is not None and info["assumed_normal_rows"] == 170
    model, info = fit_random_forest(frame, labels, unlabelled_policy="assume_normal", labelled_channel=False)
    assert model is None and "Target=NO" in info["reason"]
    labels.iloc[:50] = 0
    model, info = fit_random_forest(frame, labels)
    assert model is not None and info["excluded_unknown_rows"] == 120


def test_supervised_boundary_and_invalid_labels():
    frame = features(100)[["value"]]
    labels = pd.Series(np.arange(100) % 2, index=frame.index)
    with pytest.raises(ValueError, match="training boundary"):
        fit_random_forest(frame, labels, train_end=frame.index[50])
    labels.iloc[0] = 2
    with pytest.raises(ValueError, match="0, 1"):
        fit_random_forest(frame, labels)
