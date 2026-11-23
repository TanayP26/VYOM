"""Compatibility entry points for the chronological telemetry engine.

The streaming runner is preferred for large channels. Legacy names and columns
are retained; fitting uses training observations and returned training scores
are deliberately absent.
"""
import numpy as np
import pandas as pd

from app.detectors import IsolationForestDetector, PCAReconstructionDetector, fit_random_forest
from app.evaluation import binary_counts, chronological_split, metrics_from_counts
from app.features import FeatureConfig, TemporalFeatureBuilder


def features(s, window=30, *, cadence_seconds=None):
    """Use causal duration windows, inferred from a bounded prefix if necessary."""
    if not isinstance(s.index, pd.DatetimeIndex) or s.index.tz is None:
        raise ValueError("Telemetry features require timezone-aware timestamps")
    if len(s) < 2 and cadence_seconds is None:
        raise ValueError("At least two timestamps or an explicit cadence are required")
    inferred_rows = None
    if cadence_seconds is None:
        inferred_rows = min(len(s), 10000, max(2, int(len(s) * .7)))
        differences = np.diff(s.index[:inferred_rows].as_unit("ns").asi8) / 1e9
        cadence_seconds = float(np.median(differences))
    builder = TemporalFeatureBuilder(cadence_seconds, FeatureConfig(
        window_samples=window, min_periods=min(window, max(5, window // 3))))
    result = builder.transform(s)
    result.attrs["feature_configuration"] = builder.metadata()
    result.attrs["cadence_inferred_from_prefix_rows"] = inferred_rows
    return result


def _holdout(frame, training, fraction):
    if training is None:
        return chronological_split(frame, fraction)
    if frame.empty or training.empty:
        raise ValueError("Explicit training and test frames must be nonempty")
    if training.index[-1] >= frame.index[0]:
        raise ValueError("Explicit training must end before the scored test period")
    return training, frame


def isolation_forest(frame, contamination=.01, seed=42, *, training=None,
                     train_fraction=.7, max_train_rows=20000, batch_size=25000):
    result = pd.DataFrame({"iforest_score": np.nan, "iforest_flag": False}, index=frame.index)
    if len(frame) < 2 and training is None:
        result.attrs["status"] = "skipped: insufficient chronological observations"
        return result
    train, test = _holdout(frame, training, train_fraction)
    if len(train) < 30:
        result.attrs["status"] = "skipped: fewer than 30 training observations"
        return result
    detector = IsolationForestDetector(contamination=contamination, seed=seed,
        max_train_rows=max_train_rows, batch_size=batch_size)
    valid = np.isfinite(train.value) if "value" in train else pd.Series(True, index=train.index)
    if "feature_valid" in train:
        valid &= train.feature_valid.astype(bool)
    if int(valid.sum()) < 30:
        result.attrs["status"] = "skipped: fewer than 30 valid training observations"
        return result
    detector.fit(train, train_end=train.index[-1])
    scores = detector.score(test)
    result.loc[scores.index, scores.columns] = scores
    result.attrs["model"] = detector.metadata()
    result.attrs["status"] = "completed; training prefix unscored"
    return result


def pca_detector(frame, contamination=.01, *, alignment=None, training=None,
                 train_fraction=.7, seed=42, max_train_rows=20000):
    """Require the transformation report returned by align_channels."""
    if alignment is None:
        raise ValueError("PCA requires explicit alignment metadata: call app.detectors.align_channels first")
    result = pd.DataFrame({"pca_error": np.nan, "pca_flag": False}, index=frame.index)
    if frame.shape[1] < 2 or (len(frame) < 2 and training is None):
        result.attrs["status"] = "skipped: insufficient aligned channels or observations"
        return result
    train, test = _holdout(frame, training, train_fraction)
    if len(train.replace([np.inf, -np.inf], np.nan).dropna()) < 30:
        result.attrs["status"] = "skipped: fewer than 30 complete aligned training observations"
        return result
    detector = PCAReconstructionDetector(contamination=contamination, seed=seed,
        max_train_rows=max_train_rows).fit(train, alignment=alignment, train_end=train.index[-1])
    scores = detector.score(test)
    result.loc[scores.index, scores.columns] = scores
    result.attrs["model"] = detector.metadata()
    result.attrs["status"] = "completed; training prefix unscored"
    return result


def binary_metrics(y, p):
    return metrics_from_counts(binary_counts(y, p))


def train_random_forest(x, y, *, unlabelled_policy="exclude", labelled_channel=True,
                        train_fraction=.7, seed=42, max_train_rows=20000):
    """Split time before selecting known labels; never infer negatives from Target."""
    if len(x) < 2:
        return None, {"status": "skipped", "reason": "Insufficient chronological observations"}
    train, test = chronological_split(x, train_fraction)
    model, info = fit_random_forest(train, y.reindex(train.index),
        unlabelled_policy=unlabelled_policy, labelled_channel=labelled_channel,
        seed=seed, max_train_rows=max_train_rows, train_end=train.index[-1])
    info.update(split="chronological", train_fraction=train_fraction,
                train_end=train.index[-1].isoformat(), test_start=test.index[0].isoformat())
    if model is None:
        return None, info
    truth = y.reindex(test.index)
    if unlabelled_policy == "assume_normal":
        truth = truth.fillna(0)
    eligible = truth.notna() & np.isfinite(test).all(axis=1)
    info["test_rows"] = len(test)
    info["evaluated_test_rows"] = int(eligible.sum())
    info["unknown_test_rows"] = int(truth.isna().sum())
    info["metrics"] = binary_metrics(truth.loc[eligible].astype(int), model.predict(test.loc[eligible])) if eligible.any() else None
    return model, info
