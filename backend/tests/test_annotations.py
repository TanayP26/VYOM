import pandas as pd
from app.telemetry import categories_at
def test_interval_and_point_labels():
    t=pd.Timestamp("2000-01-01",tz="UTC")
    a=pd.DataFrame({"StartTime":[t,t+pd.Timedelta("1d")],"EndTime":[t,t+pd.Timedelta("1d")],"Category":["Anomaly","Rare Event"]})
    assert categories_at(t,a)==["Anomaly"]
