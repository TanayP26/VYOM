"""Chronological train/validation/test contracts and label-free calibration."""
from dataclasses import dataclass
import numpy as np
import pandas as pd


def split_manifest(index, train_fraction=.6, validation_fraction=.2):
    index = pd.DatetimeIndex(index)
    if index.tz is None or index.hasnans or not index.is_monotonic_increasing or not index.is_unique:
        raise ValueError("Splits require valid, unique, ordered timezone-aware timestamps")
    if not 0 < train_fraction < 1 or not 0 < validation_fraction < 1 - train_fraction:
        raise ValueError("Training, validation and test fractions must all be positive")
    train_stop = int(len(index) * train_fraction)
    validation_stop = int(len(index) * (train_fraction + validation_fraction))
    if min(train_stop, validation_stop - train_stop, len(index) - validation_stop) < 2:
        raise ValueError("Every chronological partition requires at least two rows")
    return {"train_fraction": train_fraction, "validation_fraction": validation_fraction,
            "test_fraction": 1 - train_fraction - validation_fraction,
            "train_stop": train_stop, "validation_stop": validation_stop,
            "train_rows": train_stop, "validation_rows": validation_stop - train_stop,
            "test_rows": len(index) - validation_stop,
            "train_start": index[0].isoformat(), "train_end": index[train_stop-1].isoformat(),
            "validation_start": index[train_stop].isoformat(),
            "validation_end": index[validation_stop-1].isoformat(),
            "test_start": index[validation_stop].isoformat(), "test_end": index[-1].isoformat()}


def chronological_three_way(frame, train_fraction=.6, validation_fraction=.2):
    split = split_manifest(frame.index, train_fraction, validation_fraction)
    a, b = split["train_stop"], split["validation_stop"]
    return frame.iloc[:a].copy(), frame.iloc[a:b].copy(), frame.iloc[b:].copy()


class QuantileCalibrator:
    """A fixed validation tail budget; no label-based search or test access.

    This controls an empirical validation score exceedance fraction, not the
    true false-positive probability. Validation may contain anomalies.
    """
    def __init__(self, tail_probability=.01, minimum_threshold=0):
        if not 0 < tail_probability < .5 or not np.isfinite(minimum_threshold) or minimum_threshold < 0:
            raise ValueError("Invalid calibration tail probability or threshold floor")
        self.tail_probability = tail_probability
        self.minimum_threshold = float(minimum_threshold)

    def fit(self, validation_scores, validation_end=None):
        if validation_scores.empty or not validation_scores.index.is_monotonic_increasing or not validation_scores.index.is_unique:
            raise ValueError("Validation scores must be nonempty and chronological")
        if validation_end is not None and validation_scores.index[-1] > pd.Timestamp(validation_end):
            raise ValueError("Calibration includes observations after the validation boundary")
        values = validation_scores.to_numpy(dtype=float)
        values = values[np.isfinite(values)]
        if not len(values):
            raise ValueError("No finite validation scores")
        self.threshold = max(self.minimum_threshold, float(np.quantile(values, 1-self.tail_probability, method="higher")))
        self.info = {"method": "validation empirical upper quantile, higher order statistic",
                     "tail_probability": self.tail_probability, "minimum_threshold": self.minimum_threshold,
                     "threshold": self.threshold, "validation_rows": len(values),
                     "validation_start": validation_scores.index[0].isoformat(),
                     "validation_end": validation_scores.index[-1].isoformat(),
                     "validation_exceedance_fraction": float(np.mean(values > self.threshold)),
                     "labels_used": False, "normality_assumption_for_calibration": False,
                     "limitation": "Tail budget is not a guaranteed false-alarm rate; validation can contain anomalies"}
        return self

    def predict(self, scores):
        if not hasattr(self, "threshold"):
            raise ValueError("Fit calibration on validation scores first")
        return np.isfinite(scores) & (scores > self.threshold)

    def metadata(self):
        return dict(self.info)


@dataclass
class DetectionPolicy:
    point_threshold: float
    interval_threshold: float
    min_interval_samples: int = 3
    release_ratio: float = .5

    def __post_init__(self):
        if min(self.point_threshold, self.interval_threshold) < 0 or self.min_interval_samples < 1 or not 0 < self.release_ratio <= 1:
            raise ValueError("Invalid point/interval event policy")
        self.reset_state()

    def reset_state(self):
        self._above = 0
        self._active = False
        self._last = None

    def apply(self, scores):
        if len(scores) and self._last is not None and scores.index[0] <= self._last:
            raise ValueError("Policy batches must be strictly chronological")
        points = np.isfinite(scores.point_score) & (scores.point_score > self.point_threshold)
        intervals = np.zeros(len(scores), dtype=bool)
        for i, value in enumerate(scores.interval_score.to_numpy()):
            if not np.isfinite(value):
                self._above, self._active = 0, False
            elif self._active:
                if value < self.interval_threshold * self.release_ratio:
                    self._above, self._active = 0, False
            else:
                self._above = self._above + 1 if value > self.interval_threshold else 0
                self._active = self._above >= self.min_interval_samples
            intervals[i] = self._active
        if len(scores):
            self._last = scores.index[-1]
        return pd.DataFrame({"point_flag": points, "interval_flag": intervals,
                             "temporal_flag": points | intervals}, index=scores.index)
