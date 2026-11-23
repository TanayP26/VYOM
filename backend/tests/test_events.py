import numpy as np
import pandas as pd
import pytest

from app.events import (EventGrouper, annotation_mask, correlate_event,
                        deduplicate_events, gap_events, label_samples)


def timestamp(seconds=0):
    return pd.Timestamp("2000-01-01", tz="UTC") + pd.Timedelta(seconds=seconds)


def annotations():
    return pd.DataFrame({"ID": ["interval", "point", "overlap"],
                         "Channel": ["channel_1"] * 3,
                         "StartTime": [timestamp(10), timestamp(30), timestamp(15)],
                         "EndTime": [timestamp(20), timestamp(30), timestamp(25)],
                         "Category": ["Anomaly", "Rare Event", "Communication Gap"]})


def test_inclusive_intervals_and_exact_points_with_optional_tolerance():
    ann = annotations()
    index = pd.DatetimeIndex([timestamp(x) for x in [9, 10, 20, 21, 29, 30, 31]])
    assert annotation_mask(index, ann.iloc[0], 10).tolist() == [False, True, True, False, False, False, False]
    assert annotation_mask(index, ann.iloc[1]).tolist() == [False, False, False, False, False, True, False]
    assert annotation_mask(index, ann.iloc[1], 1).tolist() == [False, False, False, False, True, True, True]


def test_overlapping_annotation_categories_and_ids_are_preserved():
    event = {"channel": "channel_1", "start": timestamp(15).isoformat(), "end": timestamp(20).isoformat()}
    result = correlate_event(event, annotations())
    assert result["annotation_ids"] == ["interval", "overlap"]
    assert result["categories"] == ["Anomaly", "Communication Gap"]
    assert correlate_event({**event, "channel": "channel_2"}, annotations())["annotation_ids"] == []


def test_unknown_rows_are_explicit_and_target_no_never_becomes_negative():
    index = pd.DatetimeIndex([timestamp(x) for x in [0, 10, 25, 30]])
    excluded = label_samples(index, annotations(), category="Anomaly")
    assert np.isnan(excluded.target.iloc[0])
    assert excluded.target.iloc[1:].tolist() == [1, 0, 0]
    assumed = label_samples(index, annotations(), unlabelled_policy="assume_normal")
    assert assumed.target.tolist() == [0, 1, 1, 1]
    unknown_channel = label_samples(index, annotations(), unlabelled_policy="assume_normal", labelled_channel=False)
    assert unknown_channel.target.isna().all()


@pytest.mark.parametrize("cadence", [3, 30, 90, 900])
def test_gap_detection_independent_of_channel_frequency(cadence):
    index = pd.DatetimeIndex([timestamp(x * cadence) for x in [0, 1, 2, 7, 8]])
    events = gap_events(index, cadence, channel="channel_1")
    assert len(events) == 1
    event = events[0]
    assert pd.Timestamp(event["start"]) > index[2]
    assert pd.Timestamp(event["end"]) < index[3]
    assert event["peak_score"] == 5
    assert event["evidence"]["estimated_missing_observations"] == 4


def test_irregular_samples_and_batch_boundary_gap():
    index = pd.DatetimeIndex([timestamp(x) for x in [11, 21, 31, 81]])
    events = gap_events(index, 10, previous_timestamp=timestamp(0))
    assert len(events) == 1
    assert events[0]["evidence"]["left_observed"] == timestamp(31).isoformat()
    # Missing values do not enter this timestamp-only interface.
    assert gap_events(pd.date_range(timestamp(), periods=4, freq="10s"), 10) == []


def test_event_grouping_crosses_batch_boundaries_and_stops_on_false_or_gap():
    grouper = EventGrouper("channel_1", 10)
    assert grouper.update(pd.DatetimeIndex([timestamp(0), timestamp(10)]), [False, True], [0, 5]) == []
    events = grouper.update(pd.DatetimeIndex([timestamp(20), timestamp(30), timestamp(80)]), [True, False, True], [8, 0, 9])
    events += grouper.flush()
    assert len(events) == 2
    assert events[0]["start"] == timestamp(10).isoformat()
    assert events[0]["end"] == timestamp(20).isoformat()
    assert events[0]["peak_score"] == 8
    assert events[0]["duration_seconds"] == 10
    assert events[0]["sample_count"] == 2
    assert events[1]["duration_seconds"] == 0


def test_consecutive_flags_separated_by_large_timestamp_gap_do_not_merge():
    grouper = EventGrouper("channel_1", 10)
    events = grouper.update(pd.DatetimeIndex([timestamp(0), timestamp(100)]), [True, True], [5, 6]) + grouper.flush()
    assert len(events) == 2


def test_event_grouping_is_identical_across_arbitrary_batch_boundaries():
    rng = np.random.default_rng(42)
    seconds = np.cumsum(rng.choice([10, 100], size=1000, p=[.98, .02]))
    index = pd.DatetimeIndex([timestamp(int(x)) for x in seconds])
    flags = rng.random(1000) > .5
    scores = rng.random(1000) * 10
    full = EventGrouper("channel_1", 10)
    expected = full.update(index, flags, scores) + full.flush()
    streaming = EventGrouper("channel_1", 10)
    actual = []
    for start in range(0, 1000, 13):
        actual += streaming.update(index[start:start + 13], flags[start:start + 13], scores[start:start + 13])
    actual += streaming.flush()
    assert actual == expected


def test_deduplication_merges_only_overlapping_events_on_same_channel():
    events = [{"channel": channel, "start": timestamp(a).isoformat(), "end": timestamp(b).isoformat(),
               "peak_score": score, "detectors": [detector], "annotation_ids": [detector]}
              for channel, a, b, score, detector in [("channel_1", 0, 20, 5, "a"),
                                                     ("channel_1", 10, 30, 8, "b"),
                                                     ("channel_2", 10, 30, 7, "c")]]
    merged = deduplicate_events(events)
    assert len(merged) == 2
    assert merged[0]["detectors"] == ["a", "b"]
    assert merged[0]["annotation_ids"] == ["a", "b"]
    assert merged[0]["peak_score"] == 8


def test_invalid_temporal_input_is_rejected():
    with pytest.raises(ValueError, match="increasing"):
        gap_events([timestamp(10), timestamp(0)], 10)
    with pytest.raises(ValueError, match="exceed one"):
        gap_events([timestamp()], 10, threshold_factor=1)
    ann = annotations()
    ann.loc[0, "EndTime"] = timestamp(0)
    with pytest.raises(ValueError, match="must not follow"):
        label_samples(pd.DatetimeIndex([timestamp()]), ann)
