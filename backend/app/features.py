"""Causal, cadence-aware telemetry features with bounded streaming history.

Every baseline uses observations in [t - window, t), excluding the scored value.
MAD is median(abs(history - median(history))), not a rolling residual proxy.
"""
from dataclasses import asdict, dataclass
import warnings

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class FeatureConfig:
    window_samples: int = 30
    scales: tuple[int, ...] = (1, 4)
    min_periods: int = 5
    epsilon: float = 1e-6
    score_cap: float = 1e6
    max_history_rows: int = 10000
    block_size: int = 512

    def __post_init__(self):
        if self.window_samples < 1 or self.min_periods < 1:
            raise ValueError("Window and minimum history must be positive")
        if not self.scales or 1 not in self.scales or any(s < 1 for s in self.scales):
            raise ValueError("Feature scales must be positive and include 1")
        if self.epsilon <= 0 or self.score_cap <= 0 or self.block_size < 1:
            raise ValueError("Epsilon, score cap and block size must be positive")
        if self.max_history_rows < self.min_periods:
            raise ValueError("History cap must cover minimum history")


class TemporalFeatureBuilder:
    """Process ordered batches; keep at most max_history_rows past observations.

    If an unusually dense burst exceeds the explicit history cap, fail with a
    useful error instead of silently changing the temporal window. Missing
    values are ignored in baselines; they never generate value-anomaly flags.
    """

    def __init__(self, cadence_seconds: float, config: FeatureConfig | None = None):
        if not np.isfinite(cadence_seconds) or cadence_seconds <= 0:
            raise ValueError("Expected cadence must be finite and positive")
        self.cadence_seconds = float(cadence_seconds)
        self.config = config or FeatureConfig()
        self._history = None
        self._last_timestamp = None

    def metadata(self):
        return {**asdict(self.config), "cadence_seconds": self.cadence_seconds,
                "windows_seconds": {str(s): self.cadence_seconds * self.config.window_samples * s
                                    for s in self.config.scales},
                "baseline_interval": "[t-window, t)", "mad": "exact history-centered MAD"}

    def transform(self, values: pd.Series | pd.DataFrame) -> pd.DataFrame:
        if isinstance(values, pd.DataFrame):
            if values.shape[1] != 1:
                raise ValueError("Build features independently for each telemetry column")
            values = values.iloc[:, 0]
        if not isinstance(values.index, pd.DatetimeIndex):
            raise ValueError("Features require a DatetimeIndex")
        if values.index.tz is None:
            raise ValueError("Feature timestamps must be timezone-aware")
        if values.index.hasnans or not values.index.is_monotonic_increasing or not values.index.is_unique:
            raise ValueError("Feature timestamps must be valid, strictly increasing and unique")
        if values.empty:
            return pd.DataFrame(index=values.index)
        values = values.copy(deep=False)
        values.index = values.index.tz_convert("UTC")
        if self._last_timestamp is not None and values.index[0] <= self._last_timestamp:
            raise ValueError("Feature batches must be chronological and non-overlapping")
        current = pd.to_numeric(values, errors="raise").astype(np.float64).replace([np.inf, -np.inf], np.nan)
        series = current if self._history is None else pd.concat([self._history, current])
        offset = len(series) - len(current)
        index = series.index
        # Pandas 3 can represent an index in microseconds: normalize explicitly.
        times = index.as_unit("ns").asi8
        array = series.to_numpy()
        out = pd.DataFrame(index=current.index)
        out["value"] = current.to_numpy()
        out["missing_value"] = current.isna().to_numpy(dtype=np.float32)
        previous = np.r_[np.nan, array[:-1]][offset:]
        difference = current.to_numpy() - previous
        out["value_change"] = difference
        denominator = np.abs(previous)
        relative = np.full(len(current), np.nan)
        safe = np.isfinite(denominator) & (denominator > self.config.epsilon)
        np.divide(difference, denominator, out=relative, where=safe)
        out["relative_change"] = relative
        gaps = np.r_[np.nan, np.diff(times).astype(np.float64) / 1e9][offset:]
        out["gap_seconds"] = gaps
        out["gap_ratio"] = gaps / self.cadence_seconds
        for scale in sorted(set(self.config.scales)):
            duration = int(round(self.cadence_seconds * self.config.window_samples * scale * 1e9))
            med, mad, q25, q75, count = self._statistics(array, times, duration, offset)
            floor = self.config.epsilon * np.maximum(1.0, np.abs(med))
            denom = np.maximum(1.4826 * mad, floor)
            score = np.divide(np.abs(current.to_numpy() - med), denom,
                              out=np.zeros(len(current)), where=np.isfinite(denom))
            score = np.nan_to_num(score, nan=0.0, posinf=self.config.score_cap, neginf=0.0)
            score = np.minimum(score, self.config.score_cap)
            if scale == 1:
                out["rolling_median"] = med
                out["rolling_mad"] = mad
                out["q25"] = q25
                out["q75"] = q75
                out["dispersion"] = q75 - q25
                out["history_count"] = count
                out["feature_valid"] = ((count >= self.config.min_periods) & np.isfinite(current)).astype(np.float32)
                out["robust_score"] = score
            else:
                out[f"median_scale_{scale}"] = med
                out[f"mad_scale_{scale}"] = mad
                out[f"robust_score_scale_{scale}"] = score
        longest = pd.Timedelta(seconds=self.cadence_seconds * self.config.window_samples * max(self.config.scales))
        keep = series.loc[series.index >= current.index[-1] - longest]
        if len(keep) > self.config.max_history_rows:
            raise ValueError("Temporal history exceeds max_history_rows; configure a larger cap or resample explicitly")
        # Retain the immediately preceding value even after a large timestamp gap.
        self._history = keep.copy()
        self._last_timestamp = current.index[-1]
        return out.astype(np.float32)

    def _statistics(self, values, times, duration, offset):
        starts = np.searchsorted(times, times[offset:] - duration, side="left")
        ends = np.arange(offset, len(values))
        widths = ends - starts
        if len(widths) and widths.max() > self.config.max_history_rows:
            raise ValueError("Temporal window exceeds max_history_rows; increase cap or resample explicitly")
        result = [np.full(len(ends), np.nan) for _ in range(4)]
        counts = np.zeros(len(ends), dtype=np.int32)
        for lo in range(0, len(ends), self.config.block_size):
            hi = min(lo + self.config.block_size, len(ends))
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
            too_short = count < self.config.min_periods
            for destination, column in zip(result, (median, mad, quartiles[0], quartiles[1])):
                column[too_short] = np.nan
                destination[lo:hi] = column
            counts[lo:hi] = count
        return *result, counts
