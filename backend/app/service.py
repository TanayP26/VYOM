from __future__ import annotations
from datetime import datetime,timezone
from pathlib import Path
import json,threading,traceback
import numpy as np
import pandas as pd
from sqlalchemy.orm import Session
from app.core import settings
from app.db import SessionLocal,AnalysisRun,DetectionEvent
from app.dataset import channel_catalog,channel_parquet,mission_summary,channel_annotations
from app.product_streaming import run_channel

_run_guard=threading.Lock()
_active_run_id:int|None=None

def reserve_run(run_id:int)->bool:
    """Reserve the single in-process analysis slot for a run id."""
    global _active_run_id
    with _run_guard:
        if _active_run_id is None:
            _active_run_id=run_id
            return True
        return _active_run_id==run_id

def active_run_id()->int|None:
    with _run_guard:
        return _active_run_id

def release_run(run_id:int)->None:
    """Release only the reservation owned by this run."""
    global _active_run_id
    with _run_guard:
        if _active_run_id==run_id:
            _active_run_id=None

def event_to_db(run_id,e):
    def dt(x):return pd.Timestamp(x).to_pydatetime()
    cats=e.get("categories") or []
    return DetectionEvent(run_id=run_id,channel=e["channel"],start=dt(e["start"]),end=dt(e["end"]),peak_time=dt(e["peak_time"]),score=float(e["peak_score"]),severity=e.get("severity","medium"),detector=e["detector"],category=",".join(cats) if cats else None,annotation_ids=e.get("annotation_ids",[]),evidence=e.get("evidence",{}))

def execute_run(run_id:int):
    db=SessionLocal();run=db.get(AnalysisRun,run_id)
    try:
        if not reserve_run(run_id):
            raise RuntimeError(f"Another analysis is already running in this API process (run #{active_run_id()})")
        run.status="running";run.started=datetime.now(timezone.utc);db.commit()
        channels=run.configuration.get("channels",[]);out=settings().resolve(settings().artifact_dir)/f"run_{run_id:05d}";out.mkdir(parents=True,exist_ok=True)
        summaries=[]
        for idx,ch in enumerate(channels,1):
            report,events=run_channel(ch,out/ch,batch_rows=int(run.configuration.get("batch_rows",settings().benchmark_batch_rows)))
            db.query(DetectionEvent).filter_by(run_id=run_id,channel=ch).delete(synchronize_session=False)
            db.add_all([event_to_db(run_id,e) for e in events]);run.processed=idx;summaries.append(report);run.summary={"channels_processed":idx,"events":sum(x["events"] for x in summaries),"last_channel":ch}
            (out/"manifest.json").write_text(json.dumps({"status":"running","run_id":run_id,"channels_requested":channels,"channels_completed":[x["channel"] for x in summaries],"reports":summaries},indent=2,default=str),encoding="utf-8")
            db.commit()
        run.status="completed";run.completed=datetime.now(timezone.utc);run.artifact_path=str(out);run.summary={"mission":"ESA Mission 1","channels_processed":len(channels),"events":sum(x["events"] for x in summaries),"combined_events":sum(x["combined_events"] for x in summaries),"scientific_note":"Retrospective VYOM protocol; inspect per-channel reports and assumptions."}
        (out/"manifest.json").write_text(json.dumps({"status":"completed","run_id":run_id,"summary":run.summary,"reports":summaries},indent=2,default=str),encoding="utf-8")
        db.commit()
    except Exception as exc:
        db.rollback();run=db.get(AnalysisRun,run_id)
        if run:
            run.status="failed";run.error=f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=4)}"[:5000];run.completed=datetime.now(timezone.utc);db.commit()
    finally:
        release_run(run_id)
        db.close()

def telemetry_sample(channel: str, start=None, end=None, points=1400):
    """Bounded display sampling only; never used by the scientific detector.

    Without a range, read a bounded chronological prefix. With a range,
    sample the matching observations with an adaptive global row stride.
    The reported range is the actual displayed interval, not the full mission.
    """
    import pyarrow.parquet as pq

    if points < 2:
        raise ValueError("At least two display points are required")

    def utc(value):
        if value is None:
            return None
        t = pd.Timestamp(value)
        return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")

    lower, upper = utc(start), utc(end)
    if lower is not None and upper is not None and lower > upper:
        raise ValueError("Start must not exceed end")
    prefix_limit = points * 20 if lower is None and upper is None else None
    sampled = []
    stride = 1
    seen = 0
    last = None
    with pq.ParquetFile(channel_parquet(channel)) as f:
        total = f.metadata.num_rows
        for batch in f.iter_batches(batch_size=50_000):
            x = batch.to_pandas()
            if "timestamp" in x:
                x = x.set_index("timestamp")
            x.index = pd.to_datetime(x.index, utc=True)
            if len(x) == 0:
                continue
            raw_end = x.index[-1]
            x = x.iloc[:, 0]
            if lower is not None:
                x = x[x.index >= lower]
            if upper is not None:
                x = x[x.index <= upper]
            if prefix_limit is not None:
                x = x.iloc[:max(0, prefix_limit - seen)]
            if len(x):
                first = (-seen) % stride
                for k in range(first, len(x), stride):
                    sampled.append((seen+k, x.index[k], x.iloc[k]))
                last = (seen+len(x)-1, x.index[-1], x.iloc[-1])
                seen += len(x)
                while len(sampled) > points * 2:
                    stride *= 2
                    sampled = [v for v in sampled if v[0] % stride == 0]
            if (upper is not None and raw_end >= upper) or (
                prefix_limit is not None and seen >= prefix_limit
            ):
                break
    if last is not None and (not sampled or sampled[-1][0] != last[0]):
        sampled.append(last)
    if len(sampled) > points:
        indices = np.linspace(0, len(sampled)-1, points, dtype=int)
        sampled = [sampled[int(i)] for i in indices]
    result = {
        "channel": channel,
        "points": [{"t": t.isoformat(), "v": None if pd.isna(v) else float(v)}
                   for _, t, v in sampled],
        "source_rows": int(total),
        "window_rows": seen,
        "returned": len(sampled),
        "sampling": "bounded_prefix" if prefix_limit is not None else "requested_range",
    }
    if sampled:
        result["range"] = {"start": sampled[0][1].isoformat(),
                           "end": sampled[-1][1].isoformat()}
    return result
