import numpy as np
import pandas as pd

from app.science import EventAccumulator


def _run(batch_size):
    index = pd.to_datetime([0, 1, 2, 3, 10, 11], unit="s", utc=True)
    flags = np.array([1, 0, 1, 0, 1, 0], dtype=bool)
    scores = np.array([4.0, 0.0, 7.0, 0.0, 5.0, 0.0])
    cadence = np.ones(len(index), dtype=float)
    grouper = EventAccumulator("channel_x", "temporal_point", bridge=2.0)
    events = []
    for start in range(0, len(index), batch_size):
        stop = min(len(index), start + batch_size)
        events += grouper.update(index[start:stop], flags[start:stop],
                                 scores[start:stop], cadence[start:stop])
    events += grouper.finish()
    return events


def test_quiet_sample_does_not_immediately_split_bridgeable_event():
    events = _run(6)
    assert len(events) == 2
    assert events[0]["start"] == "1970-01-01T00:00:00+00:00"
    assert events[0]["end"] == "1970-01-01T00:00:02+00:00"
    assert events[0]["count"] == 2
    assert events[0]["peak_score"] == 7.0
    assert events[1]["start"] == "1970-01-01T00:00:10+00:00"


def test_product_event_grouping_is_batch_invariant():
    expected = _run(6)
    for size in (1, 2, 3, 4, 5):
        assert _run(size) == expected
