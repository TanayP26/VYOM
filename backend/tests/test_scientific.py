import numpy as np
import pandas as pd
from app.cadence import SamplingRegimeTracker
from app.scientific import cadence_matched_annotations, evaluate_detector


def test_local_point_tolerance_preserves_original_truth():
    index=pd.date_range("2000",periods=20,freq="30s",tz="UTC")
    cadence=pd.Series(np.r_[np.full(10,30),np.full(10,90)],index=index)
    ann=pd.DataFrame({"ID":["point"],"StartTime":[index[12]],"EndTime":[index[12]],"Category":["Anomaly"]})
    effective=cadence_matched_annotations(ann,cadence)
    assert effective.PointToleranceSeconds.iloc[0]==45
    assert effective.OriginalStartTime.iloc[0]==ann.StartTime.iloc[0]
    assert ann.StartTime.iloc[0]==ann.EndTime.iloc[0]


def test_redundant_alerts_and_unknown_negatives_separated():
    index=pd.date_range("2000",periods=20,freq="30s",tz="UTC")
    ann=pd.DataFrame({"ID":["interval"],"StartTime":[index[5]],"EndTime":[index[12]],"Category":["Anomaly"]})
    events=[{"start":index[i].isoformat(),"end":index[i].isoformat(),"peak_score":5} for i in [6,10,18]]
    flags=np.zeros(20,bool);flags[[6,10,18]]=True
    timing=SamplingRegimeTracker(30).transform(index)
    report=evaluate_detector(index,flags,np.ones(20),events,ann,timing)
    assert report["event"]["supported_ground_truth"]["recall"]==1
    assert report["event"]["supported_ground_truth"]["precision"] is None
    burden=report["event"]["burden"]
    assert burden["redundant_overlapping_events"]==1
    assert burden["events_outside_any_label"]==1
    assert report["event"]["assumed_normal"]["fp"]==2
    assert report["sample"]["supported_ground_truth"]["confirmed_negative_samples"]==0


def test_unlabelled_channel_has_burden_but_no_ground_truth_metrics():
    index=pd.date_range("2000",periods=20,freq="30s",tz="UTC")
    ann=pd.DataFrame(columns=["ID","StartTime","EndTime","Category"])
    events=[{"start":index[3].isoformat(),"end":index[3].isoformat(),"peak_score":5}]
    report=evaluate_detector(index,np.zeros(20,bool),np.zeros(20),events,ann,SamplingRegimeTracker(30).transform(index),labelled_channel=False)
    assert report["event"]["burden"]["predicted_events"]==1
    assert report["event"]["assumed_normal"]["precision"] is None
    assert report["event"]["supported_ground_truth"]["recall"] is None
