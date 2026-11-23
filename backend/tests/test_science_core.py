from pathlib import Path
import numpy as np
import pandas as pd
from app.science import ExactOrderStore,EventAccumulator,severity,Protocol

def test_exact_order_statistics(tmp_path:Path):
    s=ExactOrderStore(tmp_path,"values")
    s.add([5,1,4,np.nan,2,3])
    assert s.count==5
    assert s.median()==3
    assert s.quantile_higher(.75)==4
    assert s.count_above(3)==2
    s.close()

def test_exact_even_median(tmp_path:Path):
    s=ExactOrderStore(tmp_path,"even");s.add([10,2,8,4]);assert s.median()==6;s.close()

def test_event_state_crosses_batch_boundary():
    idx=pd.date_range("2026-01-01",periods=6,freq="30s",tz="UTC")
    g=EventAccumulator("channel_x","temporal_point",2)
    assert g.update(idx[:2],[1,1],[4,5],[30,30])==[]
    out=g.update(idx[2:4],[1,0],[6,0],[30,30])
    assert len(out)==1 and out[0]["count"]==3 and out[0]["peak_score"]==6

def test_event_breaks_on_large_time_gap():
    idx=pd.DatetimeIndex([pd.Timestamp("2026-01-01T00:00Z"),pd.Timestamp("2026-01-01T01:00Z")])
    g=EventAccumulator("c","point",2);assert not g.update(idx[:1],[1],[5],[30]);out=g.update(idx[1:],[1],[7],[30]);out+=g.finish();assert len(out)==2

def test_severity_monotone():
    assert [severity(x) for x in [1,2,5,10]]==["low","medium","high","critical"]

def test_protocol_is_chronological():
    p=Protocol();assert p.train_fraction==.6 and p.validation_fraction==.2 and p.quantile==.99
