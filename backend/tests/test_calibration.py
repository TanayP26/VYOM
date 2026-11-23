import numpy as np
import pandas as pd
import pytest
from app.calibration import chronological_three_way, split_manifest, QuantileCalibrator, DetectionPolicy


def index(n=100):
    return pd.date_range("2000", periods=n, freq="min", tz="UTC")


def test_three_chronological_partitions_and_invalid_splits():
    frame = pd.DataFrame({"x": range(100)}, index=index())
    a, b, c = chronological_three_way(frame)
    assert [len(x) for x in (a,b,c)] == [60,20,20]
    assert a.index[-1] < b.index[0] < b.index[-1] < c.index[0]
    alt = split_manifest(frame.index, .5, .2)
    assert alt["validation_stop"] == 70
    with pytest.raises(ValueError):
        chronological_three_way(frame.iloc[::-1])
    with pytest.raises(ValueError):
        split_manifest(frame.index, .8, .3)


def test_calibration_uses_validation_only_and_strict_quantile_ties():
    validation = pd.Series(np.arange(100), index=index())
    calibration = QuantileCalibrator(.05, 3).fit(validation, validation_end=validation.index[-1])
    assert calibration.threshold == 95
    assert calibration.predict(validation).sum() == 4
    assert calibration.metadata()["labels_used"] is False
    with pytest.raises(ValueError, match="boundary"):
        calibration.fit(validation, validation_end=validation.index[-2])
    zero = QuantileCalibrator(minimum_threshold=3).fit(validation*0)
    assert zero.threshold == 3
    assert not zero.predict(validation*0).any()


def test_interval_persistence_and_hysteresis_preserve_point_detection():
    scores = pd.DataFrame({"point_score": [0,0,8,0,0,0,0,0],
                           "interval_score": [4,4,4,2,2,1,4,4]}, index=index(8))
    policy = DetectionPolicy(3,3,min_interval_samples=3)
    flags = policy.apply(scores)
    assert flags.interval_flag.tolist() == [False,False,True,True,True,False,False,False]
    assert flags.point_flag.tolist() == [False,False,True,False,False,False,False,False]
    streaming = DetectionPolicy(3,3)
    pd.testing.assert_frame_equal(flags, pd.concat([streaming.apply(scores.iloc[:3]),streaming.apply(scores.iloc[3:])]))
