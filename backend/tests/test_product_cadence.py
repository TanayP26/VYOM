import numpy as np
import pandas as pd

from app.science import AdaptiveCadence


def _times_from_deltas(deltas):
    seconds = np.r_[0.0, np.cumsum(np.asarray(deltas, dtype=float))]
    return pd.DatetimeIndex(
        pd.Timestamp("2000-01-01", tz="UTC") + pd.to_timedelta(seconds, unit="s")
    )


def test_large_persistent_delta_confirms_new_regime_instead_of_gap_flood():
    tracker = AdaptiveCadence(0.375, tolerance=0.05, confirm=8, gap_factor=3.0)
    index = _times_from_deltas([0.375] * 5 + [90.0] * 12)
    cadences, gaps = tracker.update(index)
    gaps += tracker.finish()

    assert gaps == []
    assert tracker.current == 90.0
    assert cadences[-1] == 90.0
    assert len(tracker.regimes()) == 2


def test_isolated_large_delta_remains_gap_candidate():
    tracker = AdaptiveCadence(0.375, tolerance=0.05, confirm=8, gap_factor=3.0)
    index = _times_from_deltas([0.375, 0.375, 90.0, 0.375, 0.375])
    _, gaps = tracker.update(index)
    gaps += tracker.finish()

    assert len(gaps) == 1
    assert gaps[0]["elapsed_seconds"] == 90.0
    assert gaps[0]["expected_cadence_seconds"] == 0.375
    assert gaps[0]["resolution"] == "returned_to_expected_cadence"
