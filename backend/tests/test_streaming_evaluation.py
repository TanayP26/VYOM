"""Whole-window scientific parity, causal envelope lookup and bounded recovery."""
import copy
import json

import numpy as np
import pandas as pd
import pytest

from app.scientific import cadence_matched_annotations, evaluate_detector
from app.streaming_evaluation import StreamingPointEnvelopes, StreamingScientificEvaluator


def assert_reference_fields(actual, expected):
    """New scope/provenance fields may be added; frozen fields retain meaning."""
    if isinstance(expected, dict):
        for key, value in expected.items():
            if key != "events":
                assert_reference_fields(actual[key], value)
    elif isinstance(expected, list):
        assert len(actual) == len(expected)
        for left, right in zip(actual, expected):
            assert_reference_fields(left, right)
    elif isinstance(expected, (float, np.floating)):
        assert actual == pytest.approx(expected, rel=2e-14, abs=2e-14)
    else:
        assert actual == expected


@pytest.fixture
def example():
    origin = pd.Timestamp("2001-01-01", tz="UTC")
    times = np.array([0, 1, 2, 3, 4, 5, 6, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 220, 230], dtype=float)
    index = origin + pd.to_timedelta(times, unit="s")
    cadence = np.array([1.]*8 + [10.]*12)
    timing = pd.DataFrame({"cadence_seconds": cadence,
        "previous_cadence_seconds": np.r_[1., cadence[:-1]],
        "delta_seconds": np.r_[np.nan, np.diff(times)]}, index=index)
    annotations = pd.DataFrame({
        "ID": ["before", "same", "same", "gap", "point", "after"],
        "StartTime": origin+pd.to_timedelta([-1, 5, 6, 121, 220, 250], unit="s"),
        "EndTime": origin+pd.to_timedelta([-1, 40, 50, 219, 220, 250], unit="s"),
        "Category": ["Rare Event", "Anomaly", "Anomaly", "Communication Gap", "Rare Event", "Anomaly"],
        "Channel": ["channel_1"]*6})
    events = [{"channel": "channel_1", "start": (origin+pd.Timedelta(seconds=a)).isoformat(),
               "end": (origin+pd.Timedelta(seconds=b)).isoformat(), "peak_score": 7.}
              for a,b in [(5,50),(5,5),(10,30),(80,90),(130,150),(220,220)]]
    flags = np.array([0,1,0,0,0,1,1,1,1,0,1,0,0,1,1,0,0,0,1,0], bool)
    return timing, annotations, events, flags


@pytest.mark.parametrize("batch", [1, 3, 8, 100])
def test_point_envelopes_match_strict_predecessor_and_resume(example, batch):
    timing, ann, _, _ = example
    expected = cadence_matched_annotations(ann, timing.cadence_seconds)
    stream = StreamingPointEnvelopes(ann)
    for start in range(0, len(timing), batch):
        stream.update(timing.iloc[start:start+batch])
        saved = json.loads(json.dumps(stream.to_state(), allow_nan=False))
        stream = StreamingPointEnvelopes.from_state(saved, stream.configuration_id)
    pd.testing.assert_frame_equal(stream.finish(), expected)


def test_point_envelopes_keep_nanosecond_geometry():
    index = pd.date_range("2000", periods=4, freq="ns", tz="UTC")
    ann = pd.DataFrame({"StartTime": [index[2]], "EndTime": [index[2]], "Category": ["Anomaly"]})
    cadence = pd.Series([2e-9]*4, index=index)
    stream = StreamingPointEnvelopes(ann)
    stream.update(cadence.iloc[:2])
    stream = StreamingPointEnvelopes.from_state(json.loads(json.dumps(stream.to_state())))
    stream.update(cadence.iloc[2:])
    pd.testing.assert_frame_equal(stream.finish(), cadence_matched_annotations(ann, cadence))


@pytest.mark.parametrize("batch", [1, 3, 8, 100])
@pytest.mark.parametrize("labelled", [True, False])
@pytest.mark.parametrize("gap", [True, False])
def test_metric_parity_all_views_with_restart(example, batch, labelled, gap):
    timing, ann, events, flags = example
    test = timing.iloc[5:]
    prepared = cadence_matched_annotations(ann, timing.cadence_seconds)
    expected = evaluate_detector(test.index, flags[5:], np.zeros(len(test)), events, ann, timing,
                                 labelled_channel=labelled, gap_task=gap)
    stream = StreamingScientificEvaluator(prepared, test.index[0], test.index[-1],
        labelled_channel=labelled, gap_task=gap, expected_rows=len(test))
    for start in range(0, len(test), batch):
        block = test.iloc[start:start+batch]
        stream.update_samples(block.index, flags[5+start:5+start+len(block)], block)
        stream = StreamingScientificEvaluator.from_state(json.loads(json.dumps(stream.to_state(), allow_nan=False)))
    correlated = []
    for event in events:
        correlated.append(stream.update_event(event))
        stream = StreamingScientificEvaluator.from_state(json.loads(json.dumps(stream.to_state(), allow_nan=False)))
    actual = stream.result()
    assert_reference_fields(actual, expected)
    assert correlated == expected["events"]
    assert actual["event"]["burden"]["events_outside_all_annotations"] == 1
    if not labelled and not gap:
        assert actual["sample"]["assumed_normal"]["evaluated_samples"] == 0
        assert actual["sample"]["assumed_normal"]["excluded_unknown"] == len(test)


def test_category_view_and_empty_truth_checkpoint(example):
    timing, ann, events, flags = example
    for selected in (ann, ann.iloc[:0]):
        prepared = cadence_matched_annotations(selected, timing.cadence_seconds)
        stream = StreamingScientificEvaluator(prepared, timing.index[0], timing.index[-1], category="Anomaly")
        stream.update_samples(timing.index, flags, timing)
        for event in events:
            stream.update_event(event)
        stream = StreamingScientificEvaluator.from_state(json.loads(json.dumps(stream.to_state())))
        expected = evaluate_detector(timing.index, flags, np.zeros(len(flags)), events, selected, timing, category="Anomaly")
        assert_reference_fields(stream.result(), expected)


def test_maximum_matching_reassigns_and_state_stays_annotation_bounded(example):
    timing, ann, _, flags = example
    prepared = cadence_matched_annotations(ann.iloc[1:3], timing.cadence_seconds)
    stream = StreamingScientificEvaluator(prepared, timing.index[0], timing.index[-1])
    stream.update_samples(timing.index, flags, timing)
    def event(a,b):
        return {"start": (timing.index[0]+pd.Timedelta(seconds=a)).isoformat(),
                "end": (timing.index[0]+pd.Timedelta(seconds=b)).isoformat()}
    stream.update_event(event(5,50))
    stream.update_event(event(5,5))
    assert stream.result()["event"]["assumed_normal"]["tp"] == 2
    for _ in range(10000):
        stream.update_event(event(100,100))
    assert len(json.dumps(stream.to_state())) < 15000
    for view in stream.views.values():
        assert len(view.accumulator.nodes) <= len(view.accumulator.annotations)
    result = stream.result()["event"]
    assert result["assumed_normal"]["predicted_events"] == 10002
    assert result["assumed_normal"]["tp"] == 2
    assert result["burden"]["events_outside_any_label"] == 10000


def test_exposure_batch_invariance_and_only_first_partition_delta_ignored(example):
    timing, ann, _, flags = example
    # Fractions deliberately exercise floating-point reduction differences.
    timing = timing.copy()
    timing["delta_seconds"] = np.linspace(.000001, 1.000003, len(timing))
    prepared = cadence_matched_annotations(ann, timing.cadence_seconds)
    results = []
    for batch in (1, 3, 7, len(timing)):
        stream = StreamingScientificEvaluator(prepared, timing.index[0], timing.index[-1])
        for start in range(0, len(timing), batch):
            block = timing.iloc[start:start+batch]
            stream.update_samples(block.index, flags[start:start+len(block)], block)
        results.append(stream.result()["observation_seconds"])
    assert all(value == results[0] for value in results)
    assert results[0] == pytest.approx(timing.delta_seconds.iloc[1:].sum(), rel=1e-15)


def test_state_mismatch_and_incomplete_or_overlapping_input_rejected(example):
    timing, ann, _, flags = example
    prepared = cadence_matched_annotations(ann, timing.cadence_seconds)
    stream = StreamingScientificEvaluator(prepared, timing.index[0], timing.index[-1], expected_rows=len(timing))
    stream.update_samples(timing.index[:3], flags[:3], timing.iloc[:3])
    with pytest.raises(ValueError, match="complete"):
        stream.result()
    with pytest.raises(ValueError, match="overlap"):
        stream.update_samples(timing.index[:3], flags[:3], timing.iloc[:3])
    state = stream.to_state()
    with pytest.raises(ValueError, match="identity"):
        StreamingScientificEvaluator.from_state(state, "changed")
    damaged = copy.deepcopy(state)
    damaged["configuration"]["labelled_channel"] = False
    with pytest.raises(ValueError, match="identity"):
        StreamingScientificEvaluator.from_state(damaged)
    damaged = copy.deepcopy(state)
    damaged["version"] = 999
    with pytest.raises(ValueError, match="version"):
        StreamingScientificEvaluator.from_state(damaged)


def test_point_checkpoint_rejects_changed_protocol(example):
    timing, ann, _, _ = example
    stream = StreamingPointEnvelopes(ann)
    stream.update(timing.iloc[:2])
    state = stream.to_state()
    state["configuration"]["tolerance_cadences"] = 1.
    with pytest.raises(ValueError, match="identity"):
        StreamingPointEnvelopes.from_state(state)


def test_resolved_point_envelopes_are_invariant_to_future_cadence(example):
    timing, ann, _, _ = example
    bounded_ann = ann[ann.StartTime <= timing.index[8]]
    first = StreamingPointEnvelopes(bounded_ann)
    first.update(timing.iloc[:9])
    original = first.finish()
    saved = first.to_state()
    second = StreamingPointEnvelopes.from_state(saved)
    changed = timing.iloc[9:].copy()
    changed["cadence_seconds"] *= 1000
    first.update(timing.iloc[9:])
    second.update(changed)
    pd.testing.assert_frame_equal(first.finish(), original)
    pd.testing.assert_frame_equal(second.finish(), original)


def test_checkpoint_export_does_not_alias_live_configuration(example):
    timing, ann, _, _ = example
    points = StreamingPointEnvelopes(ann)
    saved = points.to_state()
    saved["configuration"]["tolerance_cadences"] = 20
    assert points.configuration["tolerance_cadences"] == .5
    points.update(timing)
    evaluator = StreamingScientificEvaluator(points.finish(), timing.index[0], timing.index[-1])
    saved = evaluator.to_state()
    saved["configuration"]["labelled_channel"] = False
    assert evaluator.configuration["labelled_channel"] is True


def test_corrupted_matching_or_sample_state_is_rejected(example):
    timing, ann, events, flags = example
    prepared = cadence_matched_annotations(ann, timing.cadence_seconds)
    evaluator = StreamingScientificEvaluator(prepared, timing.index[0], timing.index[-1])
    evaluator.update_samples(timing.index, flags, timing)
    for event in events:
        evaluator.update_event(event)
    state = evaluator.to_state()
    broken = copy.deepcopy(state)
    matching = broken["views"]["event"]["truth_to_prediction"]
    truth = list(matching)
    assert len(truth) >= 2
    matching[truth[1]] = matching[truth[0]]
    with pytest.raises(ValueError, match="one-to-one"):
        StreamingScientificEvaluator.from_state(broken)
    broken = copy.deepcopy(state)
    broken["counts"]["tn"] += 1
    with pytest.raises(ValueError, match="processed rows"):
        StreamingScientificEvaluator.from_state(broken)


def test_long_sample_stream_keeps_constant_size_state():
    origin = pd.Timestamp("2000", tz="UTC")
    annotations = pd.DataFrame(columns=["StartTime", "EndTime", "Category"])
    prepared = cadence_matched_annotations(annotations, pd.Series([1.], index=[origin]))
    count, batch = 100000, 5000
    evaluator = StreamingScientificEvaluator(prepared, origin, origin+pd.Timedelta(seconds=count-1), expected_rows=count)
    sizes = []
    for offset in range(0, count, batch):
        index = pd.date_range(origin+pd.Timedelta(seconds=offset), periods=batch, freq="s")
        timing = pd.DataFrame({"delta_seconds": np.ones(batch), "previous_cadence_seconds": np.ones(batch)}, index=index)
        evaluator.update_samples(index, np.zeros(batch, bool), timing)
        sizes.append(len(json.dumps(evaluator.to_state())))
    result = evaluator.result()
    assert result["observation_seconds"] == count-1
    assert result["sample"]["assumed_normal"]["tn"] == count
    assert max(sizes)-min(sizes) < 100
    assert max(sizes) < 5000


def test_restart_preserves_mixed_whole_microsecond_and_nanosecond_iso_strings():
    origin = pd.Timestamp("2000", tz="UTC")
    index = pd.date_range(origin, periods=7, freq="s")
    starts = [origin+pd.Timedelta(seconds=1),
              origin+pd.Timedelta(seconds=1, microseconds=1),
              origin+pd.Timedelta(seconds=1, nanoseconds=1)]
    ann = pd.DataFrame({"StartTime": starts,
                        "EndTime": [stamp+pd.Timedelta(seconds=2) for stamp in starts],
                        "Category": ["Anomaly", "Rare Event", "Anomaly"]})
    timing = pd.DataFrame({"cadence_seconds": np.ones(len(index)),
        "previous_cadence_seconds": np.ones(len(index)),
        "delta_seconds": np.r_[np.nan, np.ones(len(index)-1)]}, index=index)
    points = StreamingPointEnvelopes(ann)
    points.update(timing.iloc[:3])
    point_state = json.loads(json.dumps(points.to_state(), allow_nan=False))
    iso_starts = [row["StartTime"] for row in point_state["configuration"]["annotations"]]
    assert "." not in iso_starts[0] and ".000001" in iso_starts[1] and ".000000001" in iso_starts[2]
    restored_points = StreamingPointEnvelopes.from_state(point_state)
    points.update(timing.iloc[3:])
    restored_points.update(timing.iloc[3:])
    pd.testing.assert_frame_equal(restored_points.finish(), points.finish())
    evaluator = StreamingScientificEvaluator(points.finish(), index[0], index[-1], expected_rows=len(index))
    evaluator.update_samples(index[:3], np.zeros(3, bool), timing.iloc[:3])
    restored = StreamingScientificEvaluator.from_state(json.loads(json.dumps(evaluator.to_state(), allow_nan=False)))
    for instance in (evaluator, restored):
        instance.update_samples(index[3:], np.zeros(4, bool), timing.iloc[3:])
    assert_reference_fields(restored.result(), evaluator.result())
    pd.testing.assert_frame_equal(restored.annotations, evaluator.annotations)
