"""Chronological and streaming scientific evaluation with explicit label policy."""
from __future__ import annotations

from collections import deque
from typing import Any

import numpy as np
import pandas as pd

from app.events import (AnnotationMatcher, label_samples,
                        tolerance_delta, utc_index, utc_timestamp)


def chronological_split(frame: pd.DataFrame, fraction: float = .7):
    if not 0 < fraction < 1:
        raise ValueError("Training fraction must be strictly between zero and one")
    if len(frame) < 2:
        raise ValueError("At least two rows are required for a chronological holdout")
    if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise ValueError("Chronological splitting requires unique sorted timestamps")
    if isinstance(frame.index, pd.DatetimeIndex) and frame.index.hasnans:
        raise ValueError("Chronological splitting does not allow missing timestamps")
    cut = min(len(frame) - 1, max(1, int(len(frame) * fraction)))
    return frame.iloc[:cut].copy(), frame.iloc[cut:].copy()


def binary_counts(y: Any, predictions: Any) -> dict[str, int]:
    truth = np.asarray(y, dtype=float)
    predicted = np.asarray(predictions)
    if truth.shape != predicted.shape or truth.ndim != 1:
        raise ValueError("Truth and prediction arrays must be aligned one-dimensional arrays")
    known = np.isfinite(truth)
    if not np.isin(truth[known], [0, 1]).all() or not np.isin(predicted, [0, 1]).all():
        raise ValueError("Binary labels and predictions must be zero or one; unknown truth may be NaN")
    truth, predicted = truth[known].astype(bool), predicted[known].astype(bool)
    return {"tp": int(np.sum(truth & predicted)), "fp": int(np.sum(~truth & predicted)),
            "tn": int(np.sum(~truth & ~predicted)), "fn": int(np.sum(truth & ~predicted)),
            "excluded_unknown": int(np.sum(~known))}


def metrics_from_counts(counts: dict[str, int]) -> dict:
    tp, fp, tn, fn = (int(counts.get(key, 0)) for key in ("tp", "fp", "tn", "fn"))
    if min(tp, fp, tn, fn) < 0:
        raise ValueError("Confusion counts cannot be negative")
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    total = tp + fp + tn + fn
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision if total else None, "recall": recall if total else None,
            "f1": f1 if total else None,
            "tp": tp, "fp": fp, "tn": tn, "fn": fn,
            "confusion_matrix": [[tn, fp], [fn, tp]], "confusion_matrix_order": [0, 1],
            "evaluated_samples": tp + fp + tn + fn,
            "excluded_unknown": int(counts.get("excluded_unknown", 0)),
            "known_negative_samples": tn + fp,
            "status": "evaluated" if total else "no_evaluable_samples",
            "zero_division": 0}


def observation_seconds(index: Any, cadence_seconds: float, previous_timestamp: Any = None,
                        gap_factor: float = 3.0) -> float:
    """Exposure is summed adjacent elapsed time excluding large timestamp gaps.

    There is no extrapolation before the first or after the last observation.
    Pass the preceding batch's last timestamp to avoid losing batch boundaries.
    """
    if not np.isfinite(cadence_seconds) or cadence_seconds <= 0 or gap_factor <= 1:
        raise ValueError("Positive cadence and gap_factor > 1 are required")
    timestamps = utc_index(index)
    if len(timestamps) == 0:
        return 0.0
    if previous_timestamp is not None:
        previous = utc_timestamp(previous_timestamp)
        if previous >= timestamps[0]:
            raise ValueError("Previous timestamp must precede the batch")
        timestamps = timestamps.insert(0, previous)
    delta = np.asarray((timestamps[1:] - timestamps[:-1]).total_seconds())
    return float(delta[delta <= gap_factor * cadence_seconds].sum())


class EventMetricAccumulator:
    """Maximum-cardinality one-to-one overlap matching in bounded memory.

    An online augmenting-path matcher stores only the predictions currently
    matched to annotations, at most one per truth record. Previously unmatched
    predictions need not be retained when only new prediction vertices arrive.
    Truth rows (not merely ID strings) are distinct; ESA IDs may span channels.
    Any inclusive temporal overlap is sufficient, not an IoU score. Point truth
    uses the configured tolerance. Broad predictions can match only one truth.
    """

    def __init__(self, annotations: pd.DataFrame, point_tolerance: Any = 0,
                 unlabelled_policy: str = "exclude", labelled_channel: bool = True):
        if unlabelled_policy not in {"exclude", "assume_normal"}:
            raise ValueError("unlabelled_policy must be exclude or assume_normal")
        self.matcher = AnnotationMatcher(annotations, point_tolerance)
        self.annotations = self.matcher.records
        self.tolerance = tolerance_delta(point_tolerance)
        self.policy = unlabelled_policy
        self.labelled_channel = labelled_channel
        self.predictions = 0
        self.truth_to_prediction: dict[int, int] = {}
        self.nodes: dict[int, tuple[dict, list[int]]] = {}

    def update(self, event: dict) -> bool:
        start, end = utc_timestamp(event["start"]), utc_timestamp(event["end"])
        if start > end:
            raise ValueError("Predicted event start must not follow its end")
        key = self.predictions
        self.predictions += 1
        adjacent = self.matcher.matching_indices(event)
        if not self.labelled_channel or not adjacent:
            return False
        self.nodes[key] = (dict(event), adjacent)
        queue = deque([key])
        parent: dict[int, tuple[int, int] | None] = {key: None}
        seen_truth: set[int] = set()
        while queue:
            prediction = queue.popleft()
            for truth_index in self.nodes[prediction][1]:
                if truth_index in seen_truth:
                    continue
                seen_truth.add(truth_index)
                incumbent = self.truth_to_prediction.get(truth_index)
                if incumbent is None:
                    while True:
                        self.truth_to_prediction[truth_index] = prediction
                        link = parent[prediction]
                        if link is None:
                            return True
                        prediction, truth_index = link
                elif incumbent not in parent:
                    parent[incumbent] = (prediction, truth_index)
                    queue.append(incumbent)
        del self.nodes[key]
        return False

    def result(self, observation_seconds: float | None = None) -> dict:
        matched = len(self.truth_to_prediction)
        unknown = self.predictions - matched
        assume_normal = self.policy == "assume_normal" and self.labelled_channel
        false_positives = unknown if assume_normal else None
        false_negatives = len(self.annotations) - matched if self.labelled_channel else None
        precision = matched / self.predictions if self.predictions else 0.0
        recall = matched / len(self.annotations) if self.annotations else 0.0
        if observation_seconds is not None and (not np.isfinite(observation_seconds) or observation_seconds < 0):
            raise ValueError("Observation exposure must be finite and nonnegative")
        return {
            "precision": precision if assume_normal else None,
            "recall": recall if self.labelled_channel else None,
            "f1": (2 * precision * recall / (precision + recall) if precision + recall else 0.0) if assume_normal else None,
            "tp": matched if self.labelled_channel else None, "fp": false_positives, "fn": false_negatives,
            "ground_truth_events": len(self.annotations), "predicted_events": self.predictions,
            "unmatched_predictions_unknown": unknown if not assume_normal else 0,
            "false_alarms_per_day": (false_positives * 86400 / observation_seconds)
                if assume_normal and observation_seconds is not None and observation_seconds > 0 else None,
            "observation_seconds": observation_seconds, "unlabelled_policy": self.policy,
            "channel_label_status": "labelled" if self.labelled_channel else "unlabelled",
            "matching": "maximum-cardinality one-to-one inclusive overlap; point tolerance only for point truth",
            "point_tolerance_seconds": self.tolerance.total_seconds(),
            "precision_note": "Unmatched predictions are assumed false alarms" if assume_normal
                else "Unmatched predictions have unknown truth; precision, F1 and false-alarm rate are unavailable",
            "matches": [{"annotation_row": truth_index, "annotation_id": self.annotations[truth_index]["ID"],
                         "prediction_index": prediction, "prediction_start": self.nodes[prediction][0]["start"],
                         "prediction_end": self.nodes[prediction][0]["end"]}
                        for truth_index, prediction in sorted(self.truth_to_prediction.items())],
        }


def evaluate_events(predictions, annotations: pd.DataFrame, point_tolerance: Any = 0,
                    observation_seconds: float | None = None, unlabelled_policy: str = "exclude",
                    labelled_channel: bool = True) -> dict:
    accumulator = EventMetricAccumulator(annotations, point_tolerance, unlabelled_policy, labelled_channel)
    for event in predictions:
        accumulator.update(event)
    return accumulator.result(observation_seconds)
