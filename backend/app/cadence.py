"""Causal sampling-regime tracking, separate from telemetry-value anomalies.

Changes require consecutive compatible deltas. Large isolated deltas become
timestamp-gap candidates only after a later observation resolves the pending
regime hypothesis. Past cadence outputs are never rewritten on confirmation.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class CadenceConfig:
    relative_tolerance: float = .05
    confirmation_samples: int = 8
    gap_factor: float = 3.0
    max_regimes: int = 100000

    def __post_init__(self):
        if not 0 < self.relative_tolerance < 1:
            raise ValueError("relative_tolerance must be in (0, 1)")
        if self.confirmation_samples < 2 or self.gap_factor <= 1:
            raise ValueError("At least two confirmation samples and gap_factor > 1 are required")
        if self.max_regimes < 1:
            raise ValueError("max_regimes must be positive")


def training_cadence(index, max_deltas=10000):
    """Estimate initial cadence from caller-supplied training timestamps only."""
    times = _index(index)
    if len(times) < 2:
        raise ValueError("At least two training timestamps are required")
    ns = times[:max_deltas + 1].as_unit("ns").asi8
    return float(np.median(np.diff(ns)) / 1e9)


def _index(index):
    result = pd.DatetimeIndex(index)
    if result.tz is None:
        raise ValueError("Sampling timestamps must be timezone-aware")
    result = result.tz_convert("UTC")
    if result.hasnans or not result.is_monotonic_increasing or not result.is_unique:
        raise ValueError("Sampling timestamps must be valid, unique and strictly increasing")
    return result


class SamplingRegimeTracker:
    """Streaming, batch-invariant segmentation using O(batch + regime cap) memory.

    Expected cadence is fixed inside each confirmed regime. A new cadence is
    the median of `confirmation_samples` consecutive out-of-regime deltas,
    each within relative_tolerance of the first candidate delta. This avoids
    adapting the baseline to one missing observation or reading future rows.
    Normal/jitter runs use vectorized bulk updates; Python processes only
    nonconforming deltas and confirmed changes.
    """
    def __init__(self, initial_cadence_seconds, config=None):
        if not np.isfinite(initial_cadence_seconds) or initial_cadence_seconds <= 0:
            raise ValueError("Initial cadence must be finite and positive")
        self.initial_cadence_seconds = float(initial_cadence_seconds)
        self.cadence_seconds = self.initial_cadence_seconds
        self.config = config or CadenceConfig()
        self.previous_timestamp = None
        self._pending = []
        self._regimes = []
        self._gaps = []
        self.rows_seen = 0
        self.resolved_gap_candidates = 0
        self.nonpersistent_deviations = 0
        self.finished = False

    def metadata(self):
        return {"configuration": asdict(self.config), "initial_cadence_seconds": self.initial_cadence_seconds,
                "initial_cadence_source": "caller-supplied training prefix",
                "method": "causal persistent-delta confirmation; median of confirmed candidate deltas",
                "confirmation": "effective_start is retrospective metadata; cadence changes only at confirmed_at",
                "gap_semantics": "resolved timestamp-gap candidates; no communication-failure cause inferred",
                "rows_seen": self.rows_seen, "confirmed_changes": max(0, len(self._regimes) - 1),
                "resolved_gap_candidates": self.resolved_gap_candidates,
                "nonpersistent_deviations": self.nonpersistent_deviations,
                "pending_observations": len(self._pending)}

    def _new_regime(self, timestamp, effective_start, cadence):
        if len(self._regimes) >= self.config.max_regimes:
            raise ValueError("Sampling regime count exceeds max_regimes; review cadence tolerance and segment budget")
        self._regimes.append({"regime_id": len(self._regimes), "start": timestamp.isoformat(),
            "effective_start": effective_start.isoformat(), "confirmed_at": timestamp.isoformat(),
            "end": timestamp.isoformat(), "cadence_seconds": float(cadence), "observations": 0,
            "duration_seconds": 0.0,
            "confirmation_lag_seconds": (timestamp - effective_start).total_seconds()})

    def _advance_regime(self, timestamp, count):
        regime = self._regimes[-1]
        regime["end"] = timestamp.isoformat()
        regime["observations"] += count
        regime["duration_seconds"] = (timestamp - pd.Timestamp(regime["start"])).total_seconds()

    def _resolve_pending(self, timestamp, reason):
        for left, right, delta, expected in self._pending:
            self.nonpersistent_deviations += 1
            if delta > self.config.gap_factor * expected:
                self._gaps.append({"start": (left + pd.Timedelta(1, "ns")).isoformat(),
                    "end": (right - pd.Timedelta(1, "ns")).isoformat(),
                    "left_observed": left.isoformat(), "right_observed": right.isoformat(),
                    "resolved_at": timestamp.isoformat(), "elapsed_seconds": float(delta),
                    "expected_cadence_seconds": float(expected), "peak_score": float(delta / expected),
                    "duration_seconds": float(delta), "detector": "adaptive_timestamp_gap",
                    "resolution": reason, "cause": "unknown"})
                self.resolved_gap_candidates += 1
        self._pending.clear()

    def transform(self, index):
        if self.finished:
            raise ValueError("Tracker is finished; create a new tracker for another stream")
        timestamps = _index(index)
        if len(timestamps) and self.previous_timestamp is not None and timestamps[0] <= self.previous_timestamp:
            raise ValueError("Sampling batches must be chronological and nonoverlapping")
        n = len(timestamps)
        previous_cadence = np.full(n, self.cadence_seconds, dtype=float)
        cadence = np.full(n, self.cadence_seconds, dtype=float)
        delta = np.empty(n, dtype=float)
        ratio = np.full(n, np.nan)
        candidate = np.zeros(n, dtype=bool)
        changes = np.zeros(n, dtype=bool)
        pending = np.zeros(n, dtype=bool)
        regime_ids = np.zeros(n, dtype=np.int32)
        if n:
            ns = timestamps.as_unit("ns").asi8
            delta[1:] = np.diff(ns) / 1e9
            delta[0] = np.nan if self.previous_timestamp is None else (timestamps[0] - self.previous_timestamp).total_seconds()
            if not self._regimes:
                self._new_regime(timestamps[0], timestamps[0], self.cadence_seconds)
            position = 0
            cache_cadence = None
            abnormal = None
            while position < n:
                expected = self.cadence_seconds
                if cache_cadence != expected:
                    abnormal = np.flatnonzero(np.isfinite(delta) &
                        (np.abs(delta / expected - 1) > self.config.relative_tolerance))
                    cache_cadence = expected
                normal = not np.isfinite(delta[position]) or abs(delta[position] / expected - 1) <= self.config.relative_tolerance
                if normal:
                    if self._pending:
                        self._resolve_pending(timestamps[position], "returned_to_expected_cadence")
                    i = np.searchsorted(abnormal, position, side="left")
                    stop = int(abnormal[i]) if i < len(abnormal) else n
                    previous_cadence[position:stop] = expected
                    cadence[position:stop] = expected
                    ratio[position:stop] = delta[position:stop] / expected
                    regime_ids[position:stop] = len(self._regimes) - 1
                    self._advance_regime(timestamps[stop - 1], stop - position)
                    position = stop
                    continue
                previous_cadence[position] = expected
                ratio[position] = delta[position] / expected
                candidate[position] = ratio[position] > self.config.gap_factor
                left = self.previous_timestamp if position == 0 else timestamps[position - 1]
                if self._pending and abs(delta[position] / self._pending[0][2] - 1) > self.config.relative_tolerance:
                    self._resolve_pending(timestamps[position], "inconsistent_new_cadence")
                self._pending.append((left, timestamps[position], float(delta[position]), expected))
                if len(self._pending) >= self.config.confirmation_samples:
                    self.cadence_seconds = float(np.median([entry[2] for entry in self._pending]))
                    self._advance_regime(timestamps[position], 0)
                    self._new_regime(timestamps[position], self._pending[0][0], self.cadence_seconds)
                    self._pending.clear()
                    changes[position] = True
                    candidate[position] = False
                else:
                    pending[position] = True
                cadence[position] = self.cadence_seconds
                regime_ids[position] = len(self._regimes) - 1
                self._advance_regime(timestamps[position], 1)
                position += 1
            self.previous_timestamp = timestamps[-1]
        self.rows_seen += n
        return pd.DataFrame({"cadence_seconds": cadence, "previous_cadence_seconds": previous_cadence,
            "delta_seconds": delta, "gap_ratio": ratio, "gap_candidate": candidate,
            "cadence_change": changes, "transition_pending": pending, "regime_id": regime_ids}, index=timestamps)

    def regimes(self):
        return [dict(regime) for regime in self._regimes]

    def drain_gaps(self):
        result, self._gaps = self._gaps, []
        return result

    def finish(self):
        """End-of-stream pending changes remain uncertain, not confirmed failures."""
        if self._pending:
            self._resolve_pending(self.previous_timestamp, "end_of_stream_unconfirmed")
        self.finished = True
        return self.drain_gaps()
