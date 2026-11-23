import numpy as np
import pandas as pd
import pytest
from app.temporal import TemporalConfig, TemporalDetector, TemporalEventGrouper


def signal(n=1000):
    return pd.Series(np.round(np.sin(np.arange(n)/20),1),
          index=pd.date_range("2000", periods=n, freq="30s", tz="UTC"))


def test_learned_floor_handles_quantized_normal_steps():
    s = pd.Series(np.tile([1.,1.,1.,1.01],100), index=signal(400).index)
    detector = TemporalDetector().fit(s.iloc[:200])
    scores = detector.score(s, 30)
    assert detector.floor >= .005-1e-12
    assert scores.point_score.max() <= 2.01
    assert np.isfinite(scores.point_score).all()


def test_postgap_point_is_scored_and_staleness_disclosed():
    s = signal(200)*.005+1
    detector = TemporalDetector().fit(s)
    detector.score(s, 30)
    point = pd.Series([.5],index=[s.index[-1]+pd.Timedelta("20h")])
    score = detector.score(point, 30)
    assert score.point_score.iloc[0] > 10
    assert bool(score.point_reference_stale.iloc[0])
    assert score.reference_age_seconds.iloc[0] == 72000


def test_temporal_batch_equivalence_and_future_invariance():
    s = signal()
    fit = s.iloc[:300]
    whole = TemporalDetector().fit(fit).score(s, 30)
    stream = TemporalDetector().fit(fit)
    actual = pd.concat([stream.score(s.iloc[:133],30),stream.score(s.iloc[133:542],30),stream.score(s.iloc[542:],30)])
    pd.testing.assert_frame_equal(whole,actual)
    modified=s.copy();modified.iloc[800:]=10000
    changed=TemporalDetector().fit(fit).score(modified,30)
    pd.testing.assert_frame_equal(whole.iloc[:800],changed.iloc[:800])


def test_constant_missing_and_dynamic_cadence():
    s=signal(300)*0+1
    s.iloc[250]=np.nan
    scores=TemporalDetector().fit(s.iloc[:200]).score(s,np.r_[np.full(150,30.),np.full(150,60.)])
    assert scores.point_score.dropna().eq(0).all()
    assert np.isnan(scores.point_score.iloc[250])
    assert scores.cadence_seconds.iloc[-1] == 60
    with pytest.raises(ValueError,match="boundary"):
        TemporalDetector().fit(s,train_end=s.index[100])


def test_cadence_aware_event_bridge_and_streaming():
    idx=signal(8).index
    flags=np.array([1,1,0,1,0,0,1,0],bool)
    scores=np.arange(8,dtype=float)
    def run(parts):
        g=TemporalEventGrouper("channel_1",bridge_cadences=2)
        events=[]
        for a,b in parts:
            events+=g.update(idx[a:b],flags[a:b],scores[a:b],30,"point")
        return events+g.flush()
    a=run([(0,8)])
    assert len(a)==2 and a[0]["sample_count"]==3 and a[0]["duration_seconds"]==90
    assert a==run([(0,3),(3,5),(5,8)])


def test_sustained_gradual_drift_has_persistent_multiscale_evidence():
    base=signal(1500)*.005+1
    base.iloc[500:]+=np.linspace(0,.25,1000)
    scores=TemporalDetector().fit(base.iloc[:400]).score(base,30)
    assert scores.interval_score.iloc[-100:].median()>3
    assert scores.training_anchor_score.iloc[-1]>3


def test_dense_history_budget_is_exposed_in_feature_output():
    s=signal(800)
    s.index=pd.date_range("2000",periods=800,freq="s",tz="UTC")
    detector=TemporalDetector(TemporalConfig(max_history_rows=480)).fit(s.iloc[:300])
    scores=detector.score(s,30)
    assert scores.truncated_history.iloc[-1]
    assert len(detector._history)==480
