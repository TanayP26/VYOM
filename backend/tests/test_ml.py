import numpy as np,pandas as pd
from app.ml import features,chronological_split,binary_metrics
def test_constant_series_is_finite():
    s=pd.Series(np.ones(100),index=pd.date_range("2000-01-01",periods=100,freq="min",tz="UTC"))
    assert np.isfinite(features(s).robust_score).all()
def test_chronological_split():
    a,b=chronological_split(pd.DataFrame({"x":range(100)}))
    assert a.index.max()<b.index.min()
def test_metrics():
    m=binary_metrics([0,0,1,1],[0,1,1,1]);assert m["tp"]==2 and m["fp"]==1
