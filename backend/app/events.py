"""Timestamp, annotation and streaming event semantics for ESA telemetry.

Benchmark intervals are closed. Point annotations are matched at their exact
timestamp unless an explicit tolerance is supplied. Detected timestamp gaps
exclude the two observed endpoints; they are candidates, not diagnosed failures.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np
import pandas as pd

CATEGORIES = ("Anomaly", "Rare Event", "Communication Gap")


def utc_timestamp(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        raise ValueError("A timestamp cannot be missing")
    return timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")


def tolerance_delta(value: Any = 0) -> pd.Timedelta:
    delta = pd.Timedelta(seconds=float(value)) if isinstance(value, (int, float, np.number)) else pd.Timedelta(value)
    if pd.isna(delta) or delta < pd.Timedelta(0):
        raise ValueError("Point-event tolerance must be finite and nonnegative")
    return delta


def utc_index(index: Any) -> pd.DatetimeIndex:
    result = pd.DatetimeIndex(pd.to_datetime(index, utc=True, errors="raise"))
    if result.hasnans or not result.is_monotonic_increasing or result.has_duplicates:
        raise ValueError("Timestamps must be nonmissing, unique and chronologically increasing")
    return result


def prepared_annotations(annotations: pd.DataFrame) -> pd.DataFrame:
    """Validate annotations without discarding points, overlaps or source IDs."""
    required = {"StartTime", "EndTime", "Category"}
    if not required.issubset(annotations):
        raise ValueError(f"Annotations require columns {sorted(required)}")
    result = annotations.copy()
    for column in ("StartTime", "EndTime"):
        result[column] = pd.to_datetime(result[column], utc=True, errors="raise")
    if result[["StartTime", "EndTime"]].isna().any().any():
        raise ValueError("Annotation timestamps cannot be missing")
    if (result.StartTime > result.EndTime).any():
        raise ValueError("Annotation start must not follow its end")
    if not result.Category.isin(CATEGORIES).all():
        raise ValueError("Annotation category is missing or outside the three ESA categories")
    if "ID" not in result:
        result["ID"] = [f"annotation_row_{i}" for i in range(len(result))]
    result["ID"] = result.ID.astype(str)
    return result.reset_index(drop=True)


def annotation_mask(index: Any, annotation: Any, point_tolerance: Any = 0) -> np.ndarray:
    """Inclusive interval matching; tolerance applies only to point annotations."""
    timestamps = pd.DatetimeIndex(pd.to_datetime(index, utc=True))
    start, end = utc_timestamp(annotation["StartTime"]), utc_timestamp(annotation["EndTime"])
    if start > end:
        raise ValueError("Annotation start must not follow its end")
    if start == end:
        delta = tolerance_delta(point_tolerance)
        start, end = start - delta, end + delta
    return np.asarray((timestamps >= start) & (timestamps <= end))


def label_samples(
    index: Any,
    annotations: pd.DataFrame,
    point_tolerance: Any = 0,
    unlabelled_policy: str = "exclude",
    category: str | None = None,
    labelled_channel: bool = True,
) -> pd.DataFrame:
    """Return target/eligible/annotated without manufacturing ground truth.

    For a category task, other annotated categories are known nonmembers. Under
    ``exclude`` unannotated rows have NaN targets. ``assume_normal`` labels them
    zero only on a labelled channel. Target=NO channels must pass
    ``labelled_channel=False`` and remain unknown under either policy.
    """
    if unlabelled_policy not in {"exclude", "assume_normal"}:
        raise ValueError("unlabelled_policy must be exclude or assume_normal")
    if category is not None and category not in CATEGORIES:
        raise ValueError(f"Unknown category: {category}")
    timestamps = utc_index(index)
    ann = prepared_annotations(annotations)
    annotated = np.zeros(len(timestamps), dtype=bool)
    positive = np.zeros(len(timestamps), dtype=bool)
    for row in ann.to_dict("records"):
        mask = annotation_mask(timestamps, row, point_tolerance)
        annotated |= mask
        if category is None or row["Category"] == category:
            positive |= mask
    eligible = annotated.copy()
    if unlabelled_policy == "assume_normal" and labelled_channel:
        eligible[:] = True
    if not labelled_channel:
        eligible[:] = False
    target = np.where(eligible, positive.astype(float), np.nan)
    return pd.DataFrame({"target": target, "eligible": eligible, "annotated": annotated}, index=timestamps)


def intervals_match(start: Any, end: Any, annotation: Any, point_tolerance: Any = 0) -> bool:
    """Any nonempty closed overlap counts; point truth uses explicit tolerance."""
    left, right = utc_timestamp(start), utc_timestamp(end)
    truth_start, truth_end = utc_timestamp(annotation["StartTime"]), utc_timestamp(annotation["EndTime"])
    if left > right or truth_start > truth_end:
        raise ValueError("Event start must not follow its end")
    if truth_start == truth_end:
        delta = tolerance_delta(point_tolerance)
        truth_start, truth_end = truth_start - delta, truth_end + delta
    return left <= truth_end and right >= truth_start


class AnnotationMatcher:
    """Prepare a channel's small annotation table once for many candidate events."""

    def __init__(self, annotations: pd.DataFrame, point_tolerance: Any = 0):
        ann = prepared_annotations(annotations)
        self.records = ann.to_dict("records")
        self.starts = pd.DatetimeIndex(ann.StartTime).as_unit("ns").asi8.copy()
        self.ends = pd.DatetimeIndex(ann.EndTime).as_unit("ns").asi8.copy()
        point = self.starts == self.ends
        delta = tolerance_delta(point_tolerance).value
        self.starts[point] -= delta
        self.ends[point] += delta
        self.channels = ann.Channel.astype(str).to_numpy() if "Channel" in ann else None

    def matching_indices(self, event: dict) -> list[int]:
        start, end = utc_timestamp(event["start"]), utc_timestamp(event["end"])
        if start > end:
            raise ValueError("Event start must not follow its end")
        hits = (start.value <= self.ends) & (end.value >= self.starts)
        if self.channels is not None and event.get("channel") is not None:
            hits &= self.channels == str(event["channel"])
        return np.flatnonzero(hits).tolist()

    def correlate(self, event: dict) -> dict:
        result = dict(event)
        hits = [self.records[i] for i in self.matching_indices(event)]
        result["annotation_ids"] = sorted({row["ID"] for row in hits})
        result["categories"] = sorted({row["Category"] for row in hits})
        return result


def correlate_event(event: dict, annotations: pd.DataFrame, point_tolerance: Any = 0) -> dict:
    return AnnotationMatcher(annotations, point_tolerance).correlate(event)


def gap_events(index: Any, cadence_seconds: float, threshold_factor: float = 3.0,
               previous_timestamp: Any = None, channel: str | None = None) -> list[dict]:
    """Find large observed timestamp separations, independent of telemetry NaNs."""
    if not np.isfinite(cadence_seconds) or cadence_seconds <= 0:
        raise ValueError("cadence_seconds must be positive and finite")
    if not np.isfinite(threshold_factor) or threshold_factor <= 1:
        raise ValueError("threshold_factor must exceed one")
    timestamps = utc_index(index)
    if len(timestamps) == 0:
        return []
    if previous_timestamp is not None:
        previous = utc_timestamp(previous_timestamp)
        if previous >= timestamps[0]:
            raise ValueError("Previous timestamp must precede this batch")
        timestamps = timestamps.insert(0, previous)
    delta_seconds = np.asarray((timestamps[1:] - timestamps[:-1]).total_seconds())
    events = []
    for position in np.flatnonzero(delta_seconds > cadence_seconds * threshold_factor):
        left, right = timestamps[position], timestamps[position + 1]
        start, end = left + pd.Timedelta(1, "ns"), right - pd.Timedelta(1, "ns")
        elapsed = float(delta_seconds[position])
        events.append({
            "channel": channel, "start": start.isoformat(), "end": end.isoformat(),
            "peak_score": elapsed / cadence_seconds, "duration_seconds": (end - start).total_seconds(),
            "detector": "timestamp_gap", "detectors": ["timestamp_gap"],
            "evidence": {"left_observed": left.isoformat(), "right_observed": right.isoformat(),
                         "elapsed_seconds": elapsed, "expected_cadence_seconds": cadence_seconds,
                         "threshold_factor": threshold_factor,
                         "estimated_missing_observations": max(0, int(np.floor(elapsed / cadence_seconds)) - 1),
                         "interpretation": "timestamp gap candidate; cause is not inferred"},
        })
    return events


class EventGrouper:
    """Keep one open event across batches; false samples and large gaps close it."""

    def __init__(self, channel: str, cadence_seconds: float, max_gap_factor: float = 1.5):
        if not np.isfinite(cadence_seconds) or cadence_seconds <= 0 or max_gap_factor < 1:
            raise ValueError("Positive cadence and max_gap_factor >= 1 are required")
        self.channel = channel
        self.maximum_gap = pd.Timedelta(seconds=cadence_seconds * max_gap_factor)
        self.current: dict | None = None
        self.previous: pd.Timestamp | None = None

    def update(self, index: Any, flags: Any, scores: Any, detector: str = "statistical",
               evidence: dict | None = None) -> list[dict]:
        timestamps = utc_index(index)
        flag_values = np.asarray(flags, dtype=bool)
        score_values = np.asarray(scores, dtype=float)
        if flag_values.shape != (len(timestamps),) or score_values.shape != (len(timestamps),):
            raise ValueError("Timestamp, flag and score lengths differ")
        if len(timestamps) and self.previous is not None and timestamps[0] <= self.previous:
            raise ValueError("Event batches must be strictly chronological and nonoverlapping")
        if not len(timestamps):
            return []
        positions = np.flatnonzero(flag_values)
        if not np.isfinite(score_values[positions]).all():
            raise ValueError("Detected samples must have finite scores")
        finished = []
        if self.current is not None and (not flag_values[0] or
                timestamps[0] - utc_timestamp(self.current["end"]) > self.maximum_gap):
            finished.extend(self.flush())
        # Scan only flagged runs in Python. Large quiet telemetry batches require
        # vectorized work, not one Timestamp conversion per original observation.
        if len(positions):
            times = timestamps.as_unit("ns").asi8
            breaks = np.flatnonzero((np.diff(positions) > 1) |
                                   (np.diff(times[positions]) > self.maximum_gap.value)) + 1
            boundaries = np.r_[0, breaks, len(positions)]
            for left, right in zip(boundaries[:-1], boundaries[1:]):
                first, last = positions[left], positions[right - 1]
                peak_position = first + int(np.argmax(score_values[first:last + 1]))
                peak_score = float(score_values[peak_position])
                if self.current is None:
                    self.current = {"channel": self.channel, "start": timestamps[first].isoformat(),
                                    "end": timestamps[last].isoformat(), "peak_score": peak_score,
                                    "duration_seconds": 0.0, "detector": detector,
                                    "detectors": [detector],
                                    "evidence": {**dict(evidence or {}), "peak_timestamp": timestamps[peak_position].isoformat()},
                                    "sample_count": int(right - left)}
                else:
                    self.current["end"] = timestamps[last].isoformat()
                    self.current["sample_count"] += int(right - left)
                    if peak_score > self.current["peak_score"]:
                        self.current["peak_score"] = peak_score
                        self.current["evidence"].update(dict(evidence or {}))
                        self.current["evidence"]["peak_timestamp"] = timestamps[peak_position].isoformat()
                    self.current["detectors"] = sorted(set(self.current["detectors"]) | {detector})
                self.current["duration_seconds"] = (timestamps[last] - utc_timestamp(self.current["start"])).total_seconds()
                if last < len(timestamps) - 1:
                    finished.extend(self.flush())
        self.previous = timestamps[-1]
        return finished

    def flush(self) -> list[dict]:
        if self.current is None:
            return []
        event, self.current = self.current, None
        return [event]


def deduplicate_events(events: Iterable[dict]) -> list[dict]:
    """Merge overlapping detections on the same channel, preserving evidence IDs."""
    ordered = sorted((dict(event) for event in events), key=lambda e: (str(e.get("channel", "")), utc_timestamp(e["start"])))
    result: list[dict] = []
    for event in ordered:
        if result and event.get("channel") == result[-1].get("channel") and utc_timestamp(event["start"]) <= utc_timestamp(result[-1]["end"]):
            merged = result[-1]
            merged["end"] = max(utc_timestamp(merged["end"]), utc_timestamp(event["end"])).isoformat()
            merged["peak_score"] = max(float(merged.get("peak_score", 0)), float(event.get("peak_score", 0)))
            merged["duration_seconds"] = (utc_timestamp(merged["end"]) - utc_timestamp(merged["start"])).total_seconds()
            for key in ("detectors", "annotation_ids", "categories"):
                merged[key] = sorted(set(merged.get(key, [])) | set(event.get(key, [])))
            original_evidence = merged.get("evidence", {})
            source_evidence = original_evidence.get("source_evidence", [dict(original_evidence)])
            source_evidence = [*source_evidence, dict(event.get("evidence", {}))]
            merged["evidence"] = {"merged_detection_count": len(source_evidence),
                                  "source_evidence": source_evidence,
                                  "reason": "overlapping detections on the same channel"}
        else:
            result.append(event)
    return result
