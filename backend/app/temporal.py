"""Separate causal point and persistent-change scores with learned scale floors."""
from dataclasses import asdict, dataclass
import warnings
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class TemporalConfig:
    point_history: int = 31
    short_cadences: int = 8
    medium_cadences: int = 120
    long_cadences: int = 480
    max_history_rows: int = 4096
    block_size: int = 128
    epsilon: float = 1e-6
    score_cap: float = 1e6

    def __post_init__(self):
        if min(self.point_history, self.short_cadences, self.medium_cadences, self.long_cadences, self.block_size) < 1:
            raise ValueError("Feature lengths must be positive")
        if self.max_history_rows < max(self.point_history, self.long_cadences) or self.epsilon <= 0:
            raise ValueError("History cap must cover nominal configured windows; epsilon must be positive")


def _series(series):
    if isinstance(series, pd.DataFrame):
        if series.shape[1] != 1:
            raise ValueError("Temporal detector takes one telemetry signal")
        series = series.iloc[:, 0]
    if not isinstance(series.index, pd.DatetimeIndex) or series.index.tz is None:
        raise ValueError("Telemetry must have timezone-aware timestamps")
    if series.index.hasnans or not series.index.is_monotonic_increasing or not series.index.is_unique:
        raise ValueError("Telemetry timestamps must be unique and chronological")
    return series.astype(float).replace([np.inf, -np.inf], np.nan)


class TemporalDetector:
    def __init__(self, config=None):
        self.config = config or TemporalConfig()
        self.reset_state()

    def reset_state(self):
        self._history = None
        self._last = None

    def fit(self, training_series, train_end=None):
        series = _series(training_series)
        if train_end is not None and series.index[-1] > pd.Timestamp(train_end):
            raise ValueError("Training extends beyond the chronological training boundary")
        clean = series.dropna().to_numpy()
        if len(clean) < 30:
            raise ValueError("At least thirty finite training observations are required")
        self.location = float(np.median(clean))
        sigma = float(1.4826 * np.median(np.abs(clean-self.location)))
        # Do not derive a difference across a missing value; that is unknown.
        differences = np.abs(series.diff().dropna().to_numpy())
        positive = differences[differences > 0]
        quantum = float(np.median(positive)) if len(positive) else 0.0
        epsilon_floor = self.config.epsilon * max(1., abs(self.location))
        self.floor = max(.5 * quantum, .1 * sigma, epsilon_floor)
        self.global_scale = max(sigma, self.floor)
        self.change_scale = max(quantum, self.floor)
        self.training = {"training_start": series.index[0].isoformat(),
             "training_end": series.index[-1].isoformat(), "training_rows": len(series),
             "training_median": self.location, "training_robust_sigma": sigma,
             "median_positive_training_step": quantum, "scale_floor": self.floor,
             "change_scale": self.change_scale,
             "floor_rule": "max(0.5*median positive adjacent training step, 0.1*training robust sigma, epsilon*level)"}
        self.reset_state()
        return self

    def metadata(self):
        return {"name": "separate_point_and_persistent_change", "configuration": asdict(self.config),
                **self.training, "point_reference": "last retained observations excluding current; age disclosed",
                "interval_windows": "causal time windows scaled by confirmed cadence at each observation",
                "history_limit": "explicit truncated_history flag if a time window exceeds retained row budget"}

    def score(self, series, cadence_seconds):
        if not hasattr(self, "floor"):
            raise ValueError("Fit the temporal detector on training data first")
        current = _series(series)
        if current.empty:
            return pd.DataFrame(index=current.index)
        if self._last is not None and current.index[0] <= self._last:
            raise ValueError("Temporal batches must be strictly chronological")
        cadence = np.broadcast_to(np.asarray(cadence_seconds, dtype=float), (len(current),)).copy()
        if not np.isfinite(cadence).all() or (cadence <= 0).any():
            raise ValueError("A positive finite cadence is required for each observation")
        joined = current if self._history is None else pd.concat([self._history, current])
        offset = len(joined)-len(current)
        values = joined.to_numpy()
        times = joined.index.as_unit("ns").asi8
        ends = np.arange(offset, len(joined))
        cfg = self.config
        point_start = np.maximum(0, ends-cfg.point_history)
        point_med, point_mad, _ = self._stats(values, point_start, ends)
        previous = np.r_[np.nan, values[:-1]][offset:]
        ages = np.r_[np.nan, np.diff(times)/1e9][offset:]
        local = np.abs(current.to_numpy()-point_med) / np.maximum(1.4826*point_mad, self.floor)
        change = np.abs(current.to_numpy()-previous) / self.change_scale
        point_score = np.fmax(local, change)
        medians, truncated = [], np.zeros(len(current), bool)
        for scale in (cfg.short_cadences, cfg.medium_cadences, cfg.long_cadences):
            desired = times[offset:] - np.rint(cadence*scale*1e9).astype(np.int64)
            starts = np.searchsorted(times, desired, side="left")
            cap_start = np.maximum(0, ends-cfg.max_history_rows)
            truncated |= starts < cap_start
            # A previous streaming batch may already have discarded older history.
            if self._history is not None and len(self._history) == cfg.max_history_rows:
                truncated |= desired < times[0]
            starts = np.maximum(starts, cap_start)
            med, _, _ = self._stats(values, starts, ends)
            medians.append(med)
        short, medium, long = medians
        shift = np.abs(short-long) / self.global_scale
        drift = np.abs(medium-long) / self.global_scale
        anchor = np.abs(long-self.location) / self.global_scale
        interval = np.fmax(np.fmax(shift, drift), anchor)
        valid = np.isfinite(current.to_numpy())
        def clean(scores):
            return np.where(valid, np.minimum(np.nan_to_num(scores, nan=0., posinf=cfg.score_cap), cfg.score_cap), np.nan)
        result = pd.DataFrame({"point_score": clean(point_score), "interval_score": clean(interval),
             "local_score": clean(local), "change_score": clean(change),
             "persistent_shift_score": clean(shift), "drift_score": clean(drift),
             "training_anchor_score": clean(anchor), "feature_valid": valid,
             "point_reference_stale": ages > 3*cadence, "reference_age_seconds": ages,
             "cadence_seconds": cadence, "truncated_history": truncated}, index=current.index)
        self._history = joined.iloc[-cfg.max_history_rows:].copy()
        self._last = current.index[-1]
        return result

    def _stats(self, values, starts, ends):
        med = np.full(len(ends), np.nan)
        mad = np.full(len(ends), np.nan)
        counts = np.zeros(len(ends), int)
        for left in range(0, len(ends), self.config.block_size):
            right = min(left+self.config.block_size, len(ends))
            width = int(np.max(ends[left:right]-starts[left:right], initial=0))
            if width == 0:
                continue
            positions = ends[left:right, None]-np.arange(1, width+1)
            valid = positions >= starts[left:right, None]
            block = values[np.maximum(positions, 0)].copy()
            block[~valid] = np.nan
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                middle = np.nanmedian(block, axis=1)
                deviation = np.nanmedian(np.abs(block-middle[:, None]), axis=1)
            med[left:right], mad[left:right] = middle, deviation
            counts[left:right] = np.isfinite(block).sum(axis=1)
        return med, mad, counts


class TemporalEventGrouper:
    """Merge close flagged runs using local cadence, with no retrospective flags."""
    def __init__(self, channel, bridge_cadences=2.):
        if bridge_cadences < 1:
            raise ValueError("bridge_cadences must be at least one")
        self.channel = channel
        self.bridge_cadences = bridge_cadences
        self.current = None
        self.last_timestamp = None
        self.last_flag_cadence = None

    def update(self, index, flags, scores, cadence_seconds, detector, evidence=None):
        index = pd.DatetimeIndex(index)
        if index.tz is None or index.hasnans or not index.is_unique or not index.is_monotonic_increasing:
            raise ValueError("Grouping requires ordered unique UTC-aware timestamps")
        if len(index) and self.last_timestamp is not None and index[0] <= self.last_timestamp:
            raise ValueError("Grouping batches overlap")
        flags, scores = np.asarray(flags, bool), np.asarray(scores, float)
        cadences = np.broadcast_to(np.asarray(cadence_seconds, float), (len(index),))
        if flags.shape != (len(index),) or scores.shape != (len(index),) or not np.isfinite(cadences).all() or (cadences <= 0).any():
            raise ValueError("Invalid grouping arrays")
        result = []
        for i in np.flatnonzero(flags):
            if not np.isfinite(scores[i]):
                raise ValueError("Flagged scores must be finite")
            timestamp = index[i]
            if self.current is not None:
                gap = (timestamp-pd.Timestamp(self.current["end"])).total_seconds()
                if gap > self.bridge_cadences * max(cadences[i], self.last_flag_cadence):
                    result.extend(self.flush())
            if self.current is None:
                self.current = {"channel": self.channel, "start": timestamp.isoformat(), "end": timestamp.isoformat(),
                    "duration_seconds": 0., "peak_score": float(scores[i]), "sample_count": 0,
                    "detector": detector, "detectors": [detector],
                    "evidence": {**(evidence or {}), "bridge_cadences": self.bridge_cadences,
                                 "peak_timestamp": timestamp.isoformat()}}
            self.current["end"] = timestamp.isoformat()
            self.current["duration_seconds"] = (timestamp-pd.Timestamp(self.current["start"])).total_seconds()
            self.current["sample_count"] += 1
            if scores[i] > self.current["peak_score"]:
                self.current["peak_score"] = float(scores[i])
                self.current["evidence"]["peak_timestamp"] = timestamp.isoformat()
            self.last_flag_cadence = cadences[i]
        if len(index):
            self.last_timestamp = index[-1]
            if self.current is not None and (index[-1]-pd.Timestamp(self.current["end"])).total_seconds() > self.bridge_cadences*max(cadences[-1], self.last_flag_cadence):
                result.extend(self.flush())
        return result

    def flush(self):
        if self.current is None:
            return []
        event, self.current = self.current, None
        return [event]
