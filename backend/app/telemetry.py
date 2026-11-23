from pathlib import Path
from zipfile import ZipFile
import pandas as pd, numpy as np

def resolve_dataset(path):
    p=Path(path).expanduser()
    options=[p,Path.cwd()/p,Path.cwd().parent/p]
    for x in options:
        if (x/"channels.csv").is_file(): return x.resolve()
    raise FileNotFoundError(f"Could not find channels.csv under {p}. Set DATASET_DIR to ESA-Mission1.")
def metadata(root):
    required={"channels.csv":["Channel","Subsystem","Physical Unit","Group","Target"],
      "labels.csv":["ID","Channel","StartTime","EndTime"],
      "anomaly_types.csv":["ID","Category","Class","Subclass"],
      "telecommands.csv":["Telecommand","Priority"]}
    d={}
    for name,cols in required.items():
        f=root/name
        if not f.is_file(): raise FileNotFoundError(f)
        x=pd.read_csv(f)
        missing=set(cols)-set(x.columns)
        if missing: raise ValueError(f"{name} missing columns {missing}")
        d[name[:-4]]=x
    d["labels"]["ID"]=d["labels"]["ID"].astype(str)
    d["anomaly_types"]["ID"]=d["anomaly_types"]["ID"].astype(str)
    d["labels"]["StartTime"]=pd.to_datetime(d["labels"]["StartTime"],utc=True,errors="raise")
    d["labels"]["EndTime"]=pd.to_datetime(d["labels"]["EndTime"],utc=True,errors="raise")
    labels, types = d["labels"], d["anomaly_types"]
    if labels[["StartTime", "EndTime"]].isna().any().any() or (labels.StartTime > labels.EndTime).any():
        raise ValueError("labels.csv contains invalid annotation timestamps or reversed intervals")
    if types.ID.duplicated().any() or d["channels"].Channel.duplicated().any():
        raise ValueError("Channel and anomaly type identifiers must be unique")
    if not set(labels.ID).issubset(types.ID):
        raise ValueError("labels.csv contains IDs absent from anomaly_types.csv")
    if not set(labels.Channel).issubset(d["channels"].Channel):
        raise ValueError("labels.csv contains channels absent from channels.csv")
    if not types.Category.isin(["Anomaly", "Rare Event", "Communication Gap"]).all():
        raise ValueError("Unsupported or missing benchmark annotation category")
    return d
def load_channel(root,channel):
    """Compatibility loader using the same strict validation as ingestion."""
    from app.storage import _channel_name, _load_validated
    frame, _ = _load_validated(Path(root), _channel_name(str(channel)))
    return frame
def annotations(labels,types,channel):
    x=labels[labels.Channel.astype(str)==str(channel)]
    return x.merge(types[["ID","Category","Class","Subclass"]],on="ID",how="left",validate="many_to_one")
def categories_at(ts,ann,point_tolerance=0):
    if ann.empty:return []
    ts = pd.to_datetime(ts, utc=True)
    tolerance = pd.Timedelta(seconds=point_tolerance) if isinstance(point_tolerance, (int, float)) else pd.Timedelta(point_tolerance)
    if tolerance < pd.Timedelta(0):
        raise ValueError("Point tolerance cannot be negative")
    point = ann.StartTime == ann.EndTime
    hit=ann[((ann.StartTime<=ts)&(ann.EndTime>=ts)) | (point & ((ann.StartTime-ts).abs()<=tolerance))]
    return sorted(set(hit.Category.dropna().astype(str)))
