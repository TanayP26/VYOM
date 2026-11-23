import numpy as np
import pandas as pd
import pytest

from app import ml
from app.detectors import align_channels


def frame():
    s = pd.Series(np.random.default_rng(7).normal(size=300),
                  index=pd.date_range("2000-01-01", periods=300, freq="90s", tz="UTC"))
    return ml.features(s)


def test_legacy_features_causal_and_cadence_aware():
    result = frame()
    assert result.attrs["feature_configuration"]["cadence_seconds"] == 90
    assert result.attrs["cadence_inferred_from_prefix_rows"] == 210
    assert result.rolling_median.iloc[30] == pytest.approx(result.value.iloc[:30].median())


def test_legacy_iforest_only_scores_chronological_holdout():
    data = frame()
    result = ml.isolation_forest(data)
    assert result.iforest_score.iloc[:210].isna().all()
    assert not result.iforest_flag.iloc[:210].any()
    assert np.isfinite(result.iforest_score.iloc[210:]).all()
    assert result.attrs["model"]["training_end"] == data.index[209].isoformat()
    with pytest.raises(ValueError, match="end before"):
        ml.isolation_forest(data.iloc[200:], training=data.iloc[:210])


def test_legacy_pca_requires_explicit_alignment():
    data = frame()
    with pytest.raises(ValueError, match="explicit alignment"):
        ml.pca_detector(data[["value", "value_change"]])
    aligned, report = align_channels({"a": data.value, "b": data.value * 2}, "90s", {"a": "V", "b": "V"})
    result = ml.pca_detector(aligned, alignment=report)
    assert result.pca_error.iloc[:210].isna().all()
    assert np.isfinite(result.pca_error.iloc[210:]).all()


def test_legacy_rf_split_before_label_filtering_and_unknowns_retained():
    data = frame()[["value"]]
    y = pd.Series(np.arange(len(data)) % 2, index=data.index, dtype=float)
    y.iloc[250:] = np.nan
    model, report = ml.train_random_forest(data, y)
    assert model is not None
    assert report["train_end"] == data.index[209].isoformat()
    assert report["test_rows"] == 90
    assert report["evaluated_test_rows"] == 40
    assert report["unknown_test_rows"] == 50
