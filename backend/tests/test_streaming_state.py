"""Scientific state/restart parity and compatibility-bound checkpoint failures."""
import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from app.cadence import SamplingRegimeTracker
from app.calibration import DetectionPolicy, QuantileCalibrator
from app.detectors import BoundedTrainingSampler, IsolationForestDetector, StatisticalDetector
from app.evaluation import EventMetricAccumulator
from app.features import TemporalFeatureBuilder
from app.streaming_state import (
    StateCompatibilityError, StateIntegrityError, StreamingTemporalEventGrouper,
    decode_state, encode_state, load_state, save_state,
)
from app.temporal import TemporalDetector, TemporalEventGrouper


IDENTITIES = {key: hashlib.sha256(key.encode()).hexdigest()
              for key in ("source", "code", "config", "protocol")}


def restored(value):
    return decode_state(encode_state(value, IDENTITIES), IDENTITIES)


def signal(count=800):
    rng = np.random.default_rng(52)
    # Preserve a pending upward transition at ordinal 122; a long gap at 420.
    deltas = np.r_[np.ones(120), np.full(100, 4.), np.ones(count - 220)]
    if count > 420:
        deltas[420] = 600
    index = pd.to_datetime(np.cumsum(deltas), unit="s", utc=True)
    values = np.round(rng.normal(0, .02, count), 2)
    values[240:320] += .5
    if count > 420:
        values[420] = 4
    values[88] = np.nan
    return pd.Series(values.astype(np.float32), index=index, name="channel_1")


@pytest.mark.parametrize("batch_size", [1, 7, 31, 128, 5000])
def test_tracker_temporal_policy_restart_matches_whole_stream(batch_size):
    series = signal()
    whole_tracker = SamplingRegimeTracker(1.)
    expected_cadence = whole_tracker.transform(series.index)
    whole_detector = TemporalDetector().fit(series.iloc[:80])
    expected_scores = whole_detector.score(series, expected_cadence.cadence_seconds)
    expected_flags = DetectionPolicy(3., 3.).apply(expected_scores)
    tracker, detector, policy = SamplingRegimeTracker(1.), TemporalDetector().fit(series.iloc[:80]), DetectionPolicy(3., 3.)
    cadences, scores, flags = [], [], []
    for start in range(0, len(series), batch_size):
        current = series.iloc[start:start + batch_size]
        cadence = tracker.transform(current.index)
        score = detector.score(current, cadence.cadence_seconds)
        flag = policy.apply(score)
        cadences.append(cadence); scores.append(score); flags.append(flag)
        tracker, detector, policy = restored((tracker, detector, policy))
    pd.testing.assert_frame_equal(pd.concat(cadences), expected_cadence)
    pd.testing.assert_frame_equal(pd.concat(scores), expected_scores)
    pd.testing.assert_frame_equal(pd.concat(flags), expected_flags)
    assert tracker.regimes() == whole_tracker.regimes()
    assert tracker.finish() == whole_tracker.finish()
    assert expected_scores.iloc[420].point_reference_stale
    assert expected_scores.iloc[420].reference_age_seconds == 600


def test_pending_cadence_and_hysteresis_survive_checkpoint():
    index = pd.to_datetime([0, 1, 2, 6, 10, 14, 18, 22, 26, 30, 34], unit="s", utc=True)
    tracker = SamplingRegimeTracker(1)
    tracker.transform(index[:6])
    clone = restored(tracker)
    assert len(clone._pending) == 3
    pd.testing.assert_frame_equal(clone.transform(index[6:]), tracker.transform(index[6:]))
    scores = pd.DataFrame({"point_score": [0.] * 11,
                           "interval_score": [0., 4, 4, 4, 2, 1.6, 1.4, 4, 4, 4, np.nan]}, index=index)
    policy = DetectionPolicy(3., 3.)
    first = policy.apply(scores.iloc[:5])
    clone = restored(policy)
    assert clone._active and clone._above == 3
    actual = pd.concat([first, clone.apply(scores.iloc[5:])])
    pd.testing.assert_frame_equal(actual, DetectionPolicy(3., 3.).apply(scores))


@pytest.mark.parametrize("batch_size", [1, 19, 73])
def test_feature_history_restart_and_future_invariance(batch_size):
    series = signal()
    expected = TemporalFeatureBuilder(1.).transform(series)
    builder = TemporalFeatureBuilder(1.)
    frames = []
    for start in range(0, len(series), batch_size):
        frames.append(builder.transform(series.iloc[start:start + batch_size]))
        builder = restored(builder)
    pd.testing.assert_frame_equal(pd.concat(frames), expected)
    changed = series.copy()
    changed.iloc[500:] += 1000
    future = TemporalFeatureBuilder(1.).transform(changed)
    pd.testing.assert_frame_equal(expected.iloc[:500], future.iloc[:500])


def test_priority_sampler_rng_and_if_model_restart_exact():
    features = TemporalFeatureBuilder(1.).transform(signal())
    features = features.loc[features.feature_valid.astype(bool)]
    columns = ["value", "value_change", "robust_score", "dispersion", "gap_ratio"]
    reference = BoundedTrainingSampler(100, 42)
    reference.update(features[columns])
    sampler = BoundedTrainingSampler(100, 42)
    sampler.update(features[columns].iloc[:123])
    sampler = restored(sampler)
    sampler.update(features[columns].iloc[123:])
    pd.testing.assert_frame_equal(sampler.sample(), reference.sample())
    assert sampler.metadata() == reference.metadata()
    model = IsolationForestDetector(max_train_rows=100, n_estimators=6).fit(features)
    clone = restored(model)
    pd.testing.assert_frame_equal(clone.score(features), model.score(features), check_exact=True)
    assert clone.metadata() == model.metadata()
    np.testing.assert_array_equal(clone.model.estimators_[0].tree_.threshold,
                                  model.model.estimators_[0].tree_.threshold)


def grouped(cls, index, flags, scores, cadence, batch_size, restart=False):
    grouper = cls("channel_1")
    events = []
    for left in range(0, len(index), batch_size):
        right = left + batch_size
        events.extend(grouper.update(index[left:right], flags[left:right], scores[left:right],
                                     cadence[left:right], "temporal", {"purpose": "parity"}))
        if restart:
            grouper = restored(grouper)
    events.extend(grouper.finish() if hasattr(grouper, "finish") else grouper.flush())
    return events


@pytest.mark.parametrize("batch_size", [1, 2, 3, 5, 16])
def test_grouping_adapter_preserves_whole_window_geometry_across_transitions(batch_size):
    index = pd.to_datetime([0, 1, 2, 3, 10, 20, 30, 31, 1000, 1001, 1002, 1030], unit="s", utc=True)
    flags = np.array([1, 0, 0, 0, 1, 1, 0, 1, 0, 1, 0, 0], dtype=bool)
    cadence = np.array([1, 1, 1, 1, 10, 10, 10, 1, 1, 1, 1, 1], dtype=float)
    scores = np.array([4, 0, 0, 0, 7, 7, 0, 5, 0, 8, 0, 0], dtype=float)
    expected = grouped(TemporalEventGrouper, index, flags, scores, cadence, len(index))
    actual = grouped(StreamingTemporalEventGrouper, index, flags, scores, cadence, batch_size, restart=True)
    assert actual == expected
    assert actual[0]["sample_count"] == 4
    # The frozen implementation is intentionally not patched: this case exposes its batch bug.
    assert grouped(TemporalEventGrouper, index, flags, scores, cadence, 1) != expected


def test_event_adapter_keeps_quiet_open_event_and_rejects_overlapping_batches():
    grouper = StreamingTemporalEventGrouper("channel_1")
    index = pd.to_datetime([0, 1, 50], unit="s", utc=True)
    assert grouper.update(index, [True, False, False], [4, 0, 0], 1, "point") == []
    assert grouper.current is not None
    with pytest.raises(ValueError, match="overlap"):
        grouper.update(index[-1:], [False], [0], 1, "point")
    assert len(grouper.finish()) == 1
    with pytest.raises(ValueError, match="finished"):
        grouper.update(index, [False] * 3, [0] * 3, 1, "point")


def test_annotation_matching_graph_duplicate_truth_restart():
    index = pd.to_datetime([0, 10, 20, 30], unit="s", utc=True)
    annotations = pd.DataFrame({"ID": ["same", "same", "overlap"],
        "Category": ["Anomaly"] * 3, "Channel": ["channel_1"] * 3,
        "StartTime": [index[0], index[0], index[1]], "EndTime": [index[2], index[2], index[3]]})
    events = [{"start": a.isoformat(), "end": b.isoformat(), "channel": "channel_1"}
              for a, b in [(index[0], index[3]), (index[0], index[0]), (index[2], index[3]), (index[3], index[3])]]
    matcher = EventMetricAccumulator(annotations, unlabelled_policy="assume_normal")
    restored_matcher = EventMetricAccumulator(annotations, unlabelled_policy="assume_normal")
    for event in events:
        matcher.update(event)
        restored_matcher.update(event)
        restored_matcher = restored(restored_matcher)
    assert restored_matcher.result(30) == matcher.result(30)
    assert matcher.result(30)["tp"] == 3
    assert len(restored_matcher.nodes) <= len(annotations)


def test_statistical_calibrator_array_and_dtype_fidelity():
    index = pd.date_range("2001", periods=4, freq="s", tz="UTC")
    scores = pd.Series([1., np.nan, 3., np.inf], index=index)
    calibrator = QuantileCalibrator(.01, 3).fit(scores)
    before = {"statistical": StatisticalDetector(), "calibrator": calibrator,
              "scalar": np.float32(-0.), "array": np.array([np.nan, np.inf, -0.], dtype=np.float32),
              "time": index, "empty": pd.DataFrame(index=index), "cursor": 420,
              "model_identity": "unchanged", "fragments": [{"ordinal": 1, "sha256": "a" * 64}]}
    after = restored(before)
    assert after["calibrator"].metadata() == calibrator.metadata()
    assert after["statistical"].metadata() == before["statistical"].metadata()
    assert after["array"].tobytes() == before["array"].tobytes()
    assert after["scalar"].tobytes() == before["scalar"].tobytes()
    pd.testing.assert_index_equal(after["time"], index)
    pd.testing.assert_frame_equal(after["empty"], before["empty"])


@pytest.mark.parametrize("key", ["source", "code", "config", "protocol"])
def test_changed_contract_hash_cannot_resume(key):
    blob = encode_state({"cursor": 50}, IDENTITIES)
    changed = {**IDENTITIES, key: "0" * 64}
    with pytest.raises(StateCompatibilityError, match="identities"):
        decode_state(blob, changed)


def test_corrupt_truncated_oversize_and_unknown_state_are_rejected(tmp_path):
    blob = encode_state({"cursor": 50}, IDENTITIES)
    for damaged in (blob[:-1], blob + b"x", blob[:-2] + b"XX"):
        with pytest.raises(StateIntegrityError):
            decode_state(damaged, IDENTITIES)
    with pytest.raises(ValueError, match="budget"):
        encode_state(np.arange(100), IDENTITIES, max_bytes=100)
    with pytest.raises(StateIntegrityError, match="oversized"):
        decode_state(blob, IDENTITIES, max_bytes=10)
    with pytest.raises(TypeError, match="Unsupported"):
        encode_state(lambda: None, IDENTITIES)
    path = tmp_path / "state.bin"
    info = save_state(path, {"cursor": 50}, IDENTITIES)
    assert load_state(path, IDENTITIES, expected_sha256=info["sha256"])["cursor"] == 50
    path.write_bytes(blob + b"x")
    with pytest.raises(StateIntegrityError, match="SHA256"):
        load_state(path, IDENTITIES, expected_sha256=info["sha256"])


def test_failed_atomic_replace_preserves_old_checkpoint(tmp_path, monkeypatch):
    from app import streaming_state
    path = tmp_path / "checkpoint.bin"
    before = save_state(path, {"cursor": 10}, IDENTITIES)
    def fail(*_):
        raise OSError("simulated interrupted replace")
    monkeypatch.setattr(streaming_state.os, "replace", fail)
    with pytest.raises(OSError, match="simulated"):
        save_state(path, {"cursor": 20}, IDENTITIES)
    assert load_state(path, IDENTITIES, expected_sha256=before["sha256"])["cursor"] == 10
    assert not list(tmp_path.glob("*.partial"))


def test_schema_version_and_unregistered_type_fail_before_restore():
    blob = encode_state({"cursor": 50}, IDENTITIES)
    header, payload = blob.split(b"\n", 1)
    data = json.loads(header)
    data["version"] += 1
    with pytest.raises(StateCompatibilityError, match="version"):
        decode_state(json.dumps(data).encode() + b"\n" + payload, IDENTITIES)
    unknown = json.dumps({"t": "registered", "class": "external.Module",
                          "state": {"t": "dict", "v": []}}).encode()
    data.update(version=1, payload_bytes=len(unknown),
                payload_sha256=hashlib.sha256(unknown).hexdigest())
    with pytest.raises(StateCompatibilityError, match="Unregistered"):
        decode_state(json.dumps(data).encode() + b"\n" + unknown, IDENTITIES)


def test_identity_fields_are_required_and_hash_shaped():
    with pytest.raises(StateCompatibilityError, match="Required identity"):
        encode_state({"cursor": 0}, {"source": "0" * 64})
    with pytest.raises(StateCompatibilityError, match="SHA256"):
        encode_state({"cursor": 0}, {**IDENTITIES, "source": "mtime-only"})
