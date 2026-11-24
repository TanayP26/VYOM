def _write_channel(path, index):
    pd.DataFrame({
        "timestamp": index,
        "value": np.linspace(0.0, 1.0, len(index), dtype=np.float32),
    }).to_parquet(path, index=False)


import numpy as np
import pandas as pd

from app.features import FeatureConfig
from app.streaming_benchmark import ParquetChannel, history_capacity_preflight

def _write(path, index):
    pd.DataFrame({"timestamp":index,"value":np.linspace(0,1,len(index),dtype=np.float32)}).to_parquet(path,index=False)

def test_dense_regime_gets_explicit_exact_capacity(tmp_path):
    sparse=pd.date_range("2000",periods=20,freq="90s",tz="UTC")
    dense=pd.date_range(sparse[-1]+pd.Timedelta(seconds=.375),periods=30000,freq="375ms",tz="UTC")
    path=tmp_path/"c.parquet"; _write(path,sparse.append(dense))
    result=history_capacity_preflight(ParquetChannel(path,batch_size=777),90.0,ceiling_rows=50000)
    assert result["status"]=="approved"
    assert result["approved_cap_rows"]>10000
    assert 28800 <= result["exact_required_rows"] <= 28802
    assert not result["feature_math_changed"] and not result["resampling"]
    assert not result["labels_used"] and not result["values_used"]

def test_preflight_abstains_over_ceiling(tmp_path):
    index=pd.date_range("2000",periods=400,freq="1s",tz="UTC")
    path=tmp_path/"c.parquet"; _write(path,index)
    cfg=FeatureConfig(window_samples=100,scales=(1,),max_history_rows=10)
    result=history_capacity_preflight(ParquetChannel(path,batch_size=37),1.0,config=cfg,ceiling_rows=50)
    assert result["status"]=="unsupported_resource_ceiling"
    assert result["exact_required_rows"]>50
    assert result["approved_cap_rows"]==10


def test_scale1_comparator_history_fits_original_guard_for_ch12_like_density(tmp_path):
    sparse = pd.date_range("2000-01-01", periods=20, freq="90s", tz="UTC")
    dense_start = sparse[-1] + pd.Timedelta(seconds=.375)
    dense = pd.date_range(dense_start, periods=12000, freq="375ms", tz="UTC")
    path = tmp_path / "channel_scale1.parquet"
    _write_channel(path, sparse.append(dense))

    source = ParquetChannel(path, batch_size=777)
    config = FeatureConfig(scales=(1,), max_history_rows=10000)
    result = history_capacity_preflight(source, 90.0, config=config, ceiling_rows=50000)

    assert result["status"] == "approved"
    assert 7200 <= result["exact_required_rows"] <= 7202
    assert result["approved_cap_rows"] == 10000
