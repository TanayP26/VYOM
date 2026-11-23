"""Separate annotation-supported recall, alert burden and assumed-normal metrics."""
import numpy as np
import pandas as pd

from app.events import AnnotationMatcher, prepared_annotations, label_samples
from app.evaluation import binary_counts, evaluate_events, metrics_from_counts


def cadence_matched_annotations(annotations, cadence, tolerance_cadences=.5):
    """Create an evaluation-only point envelope; preserve original truth times.

    Each tolerance uses the confirmed cadence at the most recent observation
    strictly before the point. The original source annotations are never edited.
    """
    ann = prepared_annotations(annotations)
    if tolerance_cadences < 0 or cadence.empty or not cadence.index.is_monotonic_increasing:
        raise ValueError("Matching needs chronological cadences and a nonnegative tolerance")
    ann["OriginalStartTime"], ann["OriginalEndTime"] = ann.StartTime.copy(), ann.EndTime.copy()
    ann["PointToleranceSeconds"] = 0.
    for i in ann.index[ann.StartTime == ann.EndTime]:
        point = ann.at[i, "StartTime"]
        position = cadence.index.searchsorted(point, side="left")-1
        # A point before this bounded stream has only the declared initial cadence.
        local = float(cadence.iloc[max(0, min(position, len(cadence)-1))])
        delta = pd.Timedelta(seconds=local*tolerance_cadences)
        ann.at[i, "PointToleranceSeconds"] = delta.total_seconds()
        ann.at[i, "StartTime"], ann.at[i, "EndTime"] = point-delta, point+delta
    return ann


def observation_exposure(cadence_frame):
    if cadence_frame.empty:
        return 0.
    delta = cadence_frame.delta_seconds.to_numpy(copy=True)
    delta[0] = np.nan  # no extrapolation from a previous partition
    expected = cadence_frame.previous_cadence_seconds.to_numpy()
    good = np.isfinite(delta) & (delta > 0) & (delta <= 3*expected)
    return float(delta[good].sum())


def _event_views(events, ann, exposure, labelled):
    matcher = AnnotationMatcher(ann)
    overlaps = sum(bool(matcher.matching_indices(event)) for event in events)
    assumed = evaluate_events(events, ann, observation_seconds=exposure,
                              unlabelled_policy="assume_normal", labelled_channel=labelled)
    supported = evaluate_events(events, ann, observation_seconds=exposure,
                                unlabelled_policy="exclude", labelled_channel=labelled)
    if not len(ann):
        assumed["recall"] = assumed["f1"] = supported["recall"] = None
    matches = assumed["tp"] or 0
    return {"supported_ground_truth": supported,
            "assumed_normal": assumed,
            "burden": {"predicted_events": len(events), "events_per_observation_day": len(events)*86400/exposure if exposure else None,
                       "events_overlapping_any_truth": overlaps,
                       "redundant_overlapping_events": overlaps-matches if labelled else None,
                       "events_outside_any_label": len(events)-overlaps,
                       "outside_label_interpretation": "unknown physical truth; assumed false alarms only under the nominal benchmark convention"}}


def evaluate_detector(index, flags, scores, events, annotations, cadence_full, *, labelled_channel=True,
                      category=None, gap_task=False, tolerance_cadences=.5):
    """Use identical final timestamps for every model; never used for calibration."""
    index = pd.DatetimeIndex(index)
    ann = cadence_matched_annotations(annotations, cadence_full.cadence_seconds, tolerance_cadences)
    ann = ann[(ann.EndTime >= index[0]) & (ann.StartTime <= index[-1])].copy()
    if gap_task:
        relevant = ann[ann.Category == "Communication Gap"]
    else:
        relevant = ann[ann.Category.isin(["Anomaly", "Rare Event"])]
    if category is not None:
        relevant = relevant[relevant.Category == category]
    exposure = observation_exposure(cadence_full.loc[index])
    matcher = AnnotationMatcher(ann)
    correlated = [matcher.correlate(event) for event in events]
    event_views = _event_views(correlated, relevant, exposure, labelled_channel)
    result = {"event": event_views,
        "observation_seconds": exposure, "elapsed_seconds": (index[-1]-index[0]).total_seconds(),
        "labelled_channel": labelled_channel,
        "point_tolerance": "half of causally confirmed local cadence before each original point",
        "truth": relevant.to_dict("records"), "events": correlated,
        "protocol": "VYOM one-to-one closed-overlap F1; not the official ESA alarming precision / affiliation protocol"}
    if gap_task:
        result["sample"] = None
        return result
    labels = label_samples(index, relevant, unlabelled_policy="assume_normal", labelled_channel=labelled_channel)
    gaps = label_samples(index, ann[ann.Category == "Communication Gap"], unlabelled_policy="exclude")
    gap_only = (gaps.target.to_numpy() == 1) & ~labels.annotated.to_numpy()
    labels.loc[gap_only, "target"] = np.nan
    counts = binary_counts(labels.target.to_numpy(), np.asarray(flags, bool))
    sample = metrics_from_counts(counts)
    if not (counts["tp"]+counts["fn"]):
        sample["recall"] = sample["f1"] = None
    result["sample"] = {"assumed_normal": sample,
        "supported_ground_truth": {"labelled_positive_recall": counts["tp"]/(counts["tp"]+counts["fn"]) if counts["tp"]+counts["fn"] else None,
           "labelled_positive_samples": counts["tp"]+counts["fn"], "confirmed_negative_samples": 0,
           "precision": None, "f1": None, "note": "No independently verified normal observations were supplied"},
        "burden": {"flagged_samples": int(np.sum(flags)), "flagged_sample_fraction": float(np.mean(flags)),
                   "unlabelled_samples": int((~labels.annotated).sum())}}
    result["per_category"] = {name: _event_views(correlated, relevant[relevant.Category == name], exposure, labelled_channel)
                               for name in ("Anomaly", "Rare Event")}
    points = relevant.OriginalStartTime == relevant.OriginalEndTime
    result["per_geometry"] = {"point": _event_views(correlated, relevant[points], exposure, labelled_channel),
                              "interval": _event_views(correlated, relevant[~points], exposure, labelled_channel)}
    return result
