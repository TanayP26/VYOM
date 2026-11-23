import numpy as np
import pandas as pd
import pytest

from app.evaluation import (EventMetricAccumulator, binary_counts,
                            chronological_split, evaluate_events,
                            metrics_from_counts, observation_seconds)


def timestamp(seconds=0):
    return pd.Timestamp("2000-01-01", tz="UTC") + pd.Timedelta(seconds=seconds)


def truth(intervals):
    return pd.DataFrame({"ID": [f"id_{i}" for i in range(len(intervals))],
                         "Channel": ["channel_1"] * len(intervals),
                         "StartTime": [timestamp(a) for a, _ in intervals],
                         "EndTime": [timestamp(b) for _, b in intervals],
                         "Category": ["Anomaly"] * len(intervals)})


def prediction(start, end, channel="channel_1"):
    return {"channel": channel, "start": timestamp(start).isoformat(), "end": timestamp(end).isoformat()}


def test_chronological_split_keeps_future_out_of_training():
    frame = pd.DataFrame({"x": range(10)}, index=pd.date_range(timestamp(), periods=10, freq="10s"))
    train, test = chronological_split(frame, .6)
    assert len(train) == 6 and len(test) == 4
    assert train.index.max() < test.index.min()
    changed = frame.copy()
    changed.loc[test.index, "x"] = 100000
    pd.testing.assert_frame_equal(chronological_split(changed, .6)[0], train)


@pytest.mark.parametrize("index", [[2, 1, 3], [1, 1, 2]])
def test_chronological_split_rejects_unsorted_and_duplicate_index(index):
    with pytest.raises(ValueError, match="unique sorted"):
        chronological_split(pd.DataFrame({"x": [1, 2, 3]}, index=index))


def test_sample_metrics_and_unknown_exclusion():
    counts = binary_counts([0, 0, 1, 1, np.nan], [0, 1, 1, 0, 1])
    report = metrics_from_counts(counts)
    assert report["confusion_matrix"] == [[1, 1], [1, 1]]
    assert report["precision"] == report["recall"] == report["f1"] == .5
    assert report["excluded_unknown"] == 1


def test_empty_sample_evaluation_is_unavailable_not_measured_zero():
    report = metrics_from_counts(binary_counts([], []))
    assert report["precision"] is report["recall"] is report["f1"] is None
    assert report["status"] == "no_evaluable_samples"


def test_one_truth_cannot_be_counted_twice():
    report = evaluate_events([prediction(0, 5), prediction(6, 10)], truth([(0, 10)]), unlabelled_policy="assume_normal")
    assert report["tp"] == 1 and report["fp"] == 1 and report["fn"] == 0
    assert report["precision"] == .5


def test_one_broad_prediction_cannot_count_multiple_truth_events():
    report = evaluate_events([prediction(0, 100)], truth([(0, 10), (90, 100)]), unlabelled_policy="assume_normal")
    assert report["tp"] == 1 and report["fn"] == 1


def test_maximum_matching_finds_augmenting_path_instead_of_greedy_undercount():
    report = evaluate_events([prediction(0, 30), prediction(0, 10)], truth([(0, 10), (20, 30)]), unlabelled_policy="assume_normal")
    assert report["tp"] == 2 and report["fn"] == 0
    assert len({match["prediction_index"] for match in report["matches"]}) == 2


def test_point_tolerance_and_channel_identity():
    ann = truth([(30, 30)])
    assert evaluate_events([prediction(29, 29)], ann)["tp"] == 0
    assert evaluate_events([prediction(29, 29)], ann, point_tolerance=1)["tp"] == 1
    assert evaluate_events([prediction(30, 30, "channel_2")], ann)["tp"] == 0


def test_unknown_predictions_not_falsely_counted_as_false_alarms():
    report = evaluate_events([prediction(0, 10), prediction(100, 110)], truth([(0, 10)]))
    assert report["tp"] == 1 and report["unmatched_predictions_unknown"] == 1
    assert report["precision"] is None and report["f1"] is None and report["fp"] is None


def test_target_no_stays_unlabelled_even_with_assumed_normal_policy():
    report = evaluate_events([prediction(100, 110)], truth([]), unlabelled_policy="assume_normal", labelled_channel=False)
    assert report["precision"] is None and report["fp"] is None and report["recall"] is None


def test_streaming_event_memory_bounded_by_annotations():
    accumulator = EventMetricAccumulator(truth([(0, 10), (20, 30)]), unlabelled_policy="assume_normal")
    for i in range(1000):
        accumulator.update(prediction(i, i))
        assert len(accumulator.nodes) <= 2
    assert accumulator.result()["predicted_events"] == 1000


def test_exposure_excludes_timestamp_gaps_and_preserves_batch_boundaries():
    index = pd.DatetimeIndex([timestamp(x) for x in [0, 10, 20, 100, 110]])
    whole = observation_seconds(index, 10)
    chunks = observation_seconds(index[:3], 10) + observation_seconds(index[3:], 10, previous_timestamp=index[2])
    assert whole == chunks == 30
    result = evaluate_events([prediction(500, 500)], truth([]), observation_seconds=86400, unlabelled_policy="assume_normal")
    assert result["false_alarms_per_day"] == 1
