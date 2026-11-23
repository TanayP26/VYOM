import numpy as np
import pandas as pd
import pytest

from app.cadence import CadenceConfig, SamplingRegimeTracker, training_cadence


def timeline(deltas):
    return pd.Timestamp("2000-01-01", tz="UTC") + pd.to_timedelta(np.r_[0, np.cumsum(deltas)], unit="s")


def test_normal_jitter_does_not_create_regimes_or_gaps():
    index = timeline([90, 90.003, 89.997, 90] * 100)
    tracker = SamplingRegimeTracker(90)
    result = tracker.transform(index)
    assert (result.cadence_seconds == 90).all()
    assert not result.cadence_change.any()
    assert tracker.drain_gaps() == []
    assert len(tracker.regimes()) == 1
    assert tracker.regimes()[0]["observations"] == len(index)


@pytest.mark.parametrize("new_cadence", [3, 900])
def test_persistent_switch_is_confirmed_causally(new_cadence):
    index = timeline([90] * 10 + [new_cadence] * 20)
    tracker = SamplingRegimeTracker(90, CadenceConfig(confirmation_samples=4))
    result = tracker.transform(index)
    assert (result.cadence_seconds.iloc[:14] == 90).all()
    assert (result.cadence_seconds.iloc[14:] == new_cadence).all()
    assert result.cadence_change.sum() == 1
    assert result.cadence_change.iloc[14]
    assert tracker.drain_gaps() == []
    regimes = tracker.regimes()
    assert regimes[1]["effective_start"] == index[10].isoformat()
    assert regimes[1]["confirmed_at"] == index[14].isoformat()
    assert sum(r["observations"] for r in regimes) == len(index)
    assert sum(r["duration_seconds"] for r in regimes) == (index[-1] - index[0]).total_seconds()


def test_isolated_gap_is_resolved_on_return_not_made_a_regime():
    index = timeline([30] * 5 + [300] + [30] * 8)
    tracker = SamplingRegimeTracker(30)
    result = tracker.transform(index[:7])
    assert result.gap_candidate.iloc[-1]
    assert tracker.drain_gaps() == []
    tracker.transform(index[7:])
    gaps = tracker.drain_gaps()
    assert len(gaps) == 1
    assert gaps[0]["elapsed_seconds"] == 300
    assert gaps[0]["resolution"] == "returned_to_expected_cadence"
    assert gaps[0]["resolved_at"] == index[7].isoformat()
    assert gaps[0]["cause"] == "unknown"
    assert len(tracker.regimes()) == 1


def test_batch_invariance_and_future_invariance():
    index = timeline([30] * 12 + [300] + [30] * 4 + [3] * 20 + [900] * 12 + [3] * 10)
    whole = SamplingRegimeTracker(30, CadenceConfig(confirmation_samples=4))
    expected = whole.transform(index)
    whole_gaps = whole.finish()
    batches = SamplingRegimeTracker(30, CadenceConfig(confirmation_samples=4))
    frames, gaps = [], []
    for lo in range(0, len(index), 3):
        frames.append(batches.transform(index[lo:lo + 3]))
        gaps.extend(batches.drain_gaps())
    gaps.extend(batches.finish())
    pd.testing.assert_frame_equal(expected, pd.concat(frames))
    assert whole.regimes() == batches.regimes()
    assert whole_gaps == gaps
    prefix = SamplingRegimeTracker(30, CadenceConfig(confirmation_samples=4))
    pd.testing.assert_frame_equal(expected.iloc[:35], prefix.transform(index[:35]))


def test_inconsistent_slow_deltas_do_not_imply_communication_failure():
    index = timeline([30] * 5 + [300, 600, 1200, 30])
    tracker = SamplingRegimeTracker(30)
    tracker.transform(index)
    gaps = tracker.finish()
    assert len(gaps) == 3
    assert all(gap["cause"] == "unknown" for gap in gaps)
    assert len(tracker.regimes()) == 1


def test_unconfirmed_terminal_change_is_explicit():
    tracker = SamplingRegimeTracker(30)
    tracker.transform(timeline([30] * 5 + [300] * 2))
    gaps = tracker.finish()
    assert len(gaps) == 2
    assert all(gap["resolution"] == "end_of_stream_unconfirmed" for gap in gaps)
    with pytest.raises(ValueError, match="finished"):
        tracker.transform(timeline([30]))


def test_validation_and_training_cadence():
    index = timeline([90] * 20)
    assert training_cadence(index) == 90
    with pytest.raises(ValueError, match="timezone"):
        SamplingRegimeTracker(90).transform(index.tz_localize(None))
    with pytest.raises(ValueError, match="strictly increasing"):
        SamplingRegimeTracker(90).transform(index[::-1])
    tracker = SamplingRegimeTracker(90)
    tracker.transform(index[:5])
    with pytest.raises(ValueError, match="nonoverlapping"):
        tracker.transform(index[4:])
    with pytest.raises(ValueError, match="Initial cadence"):
        SamplingRegimeTracker(0)


def test_regime_budget_is_enforced():
    tracker = SamplingRegimeTracker(30, CadenceConfig(confirmation_samples=2, max_regimes=1))
    with pytest.raises(ValueError, match="max_regimes"):
        tracker.transform(timeline([30] * 5 + [300] * 2))
