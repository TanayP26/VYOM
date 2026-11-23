import json
from dataclasses import replace
import numpy as np
import pandas as pd
import pytest
from app.comparison import ComparisonConfig, run_window


def data():
    idx=pd.date_range("2000",periods=500,freq="30s",tz="UTC")
    values=np.round(np.sin(np.arange(500)/20),1)*.01+1
    values[450]=.5
    raw=pd.Series(values,index=idx,name="value")
    ann=pd.DataFrame({"ID":["point"],"Channel":["channel_1"],"StartTime":[idx[450]],"EndTime":[idx[450]],"Category":["Anomaly"]})
    return raw,ann


def test_comparison_artifacts_and_postfreeze_evaluation(tmp_path):
    raw,ann=data()
    cfg=ComparisonConfig(max_rows=500,max_train_rows=100,n_estimators=8,batch_size=73)
    report=run_window(raw,"channel_1",ann,tmp_path,config=cfg)
    frozen=json.loads((tmp_path/"model_configuration.json").read_text())
    assert frozen["labels_used_for_training_or_calibration"] is False
    assert report["split"]["train_rows"]==300 and report["split"]["test_rows"]==100
    assert set(report["models"])=={"robust_statistical","isolation_forest","temporal_point","temporal_interval","improved_temporal","combined"}
    assert report["models"]["temporal_point"]["event"]["supported_ground_truth"]["recall"]==1
    assert (tmp_path/"predictions.parquet").exists()
    assert report["models"]["combined"]["resources"]["peak_sampled_process_rss_mib"]>0


def test_final_values_and_labels_cannot_change_calibration(tmp_path):
    raw,ann=data()
    cfg=ComparisonConfig(max_rows=500,max_train_rows=100,n_estimators=8,batch_size=73)
    first=run_window(raw,"channel_1",ann,tmp_path/"first",config=cfg)
    changed=raw.copy();changed.iloc[400:]=np.arange(100)*100
    changed_ann=ann.copy();changed_ann["StartTime"]=raw.index[420];changed_ann["EndTime"]=raw.index[470]
    second=run_window(changed,"channel_1",changed_ann,tmp_path/"second",config=cfg)
    a=json.loads((tmp_path/"first/model_configuration.json").read_text())
    b=json.loads((tmp_path/"second/model_configuration.json").read_text())
    assert a["calibration"]==b["calibration"]
    assert a["models"]==b["models"]
    assert first["calibration"]==second["calibration"]


def test_pilot_bound_refuses_unbounded_analysis():
    with pytest.raises(ValueError,match="full analysis"):
        ComparisonConfig(max_rows=1000000)


def test_combined_keeps_finite_postgap_score_when_if_abstains(tmp_path):
    raw,ann=data()
    shifted=raw.index[:450].append(raw.index[450:]+pd.Timedelta("20h"))
    raw.index=shifted
    ann["StartTime"]=shifted[450];ann["EndTime"]=shifted[450]
    report=run_window(raw,"channel_1",ann,tmp_path,config=ComparisonConfig(
        max_rows=500,max_train_rows=100,n_estimators=8,batch_size=73))
    assert report["models"]["combined"]["event"]["supported_ground_truth"]["recall"]==1
    predictions=pd.read_parquet(tmp_path/"predictions.parquet")
    assert np.isnan(predictions.loc[shifted[450],"isolation_forest_score"])
    assert np.isfinite(predictions.loc[shifted[450],"combined_score"])
