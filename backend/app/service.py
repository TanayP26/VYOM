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
from app.science import run_channel

_run_lock=threading.Lock()

def event_to_db(run_id,e):
    def dt(x):return pd.Timestamp(x).to_pydatetime()
    cats=e.get("categories") or []
    return DetectionEvent(run_id=run_id,channel=e["channel"],start=dt(e["start"]),end=dt(e["end"]),peak_time=dt(e["peak_time"]),score=float(e["peak_score"]),severity=e.get("severity","medium"),detector=e["detector"],category=",".join(cats) if cats else None,annotation_ids=e.get("annotation_ids",[]),evidence=e.get("evidence",{}))

def execute_run(run_id:int):
    db=SessionLocal();run=db.get(AnalysisRun,run_id)
    try:
        if not _run_lock.acquire(blocking=False):raise RuntimeError("Another analysis is already running in this API process")
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
        if _run_lock.locked():_run_lock.release()
        db.close()

def telemetry_sample(channel:str,start=None,end=None,points=1400):
    import pyarrow.parquet as pq
    path=channel_parquet(channel);frames=[]
    with pq.ParquetFile(path) as f:
        total=f.metadata.num_rows;stride=max(1,total//max(points*8,1))
        seen=0
        for batch in f.iter_batches(batch_size=50_000):
            x=batch.to_pandas();
            if "timestamp" in x:x=x.set_index("timestamp")
            x.index=pd.to_datetime(x.index,utc=True);x=x.iloc[:,[0]]
            if start:x=x[x.index>=pd.Timestamp(start)]
            if end:x=x[x.index<=pd.Timestamp(end)]
            if len(x):frames.append(x.iloc[::stride]);seen+=len(x)
            if start and end and len(x) and x.index[-1]>=pd.Timestamp(end):break
            if seen>points*20 and not start and not end:break
    if not frames:return {"channel":channel,"points":[],"source_rows":0}
    x=pd.concat(frames).sort_index();
    if len(x)>points:
        idx=pd.unique(np.linspace(0,len(x)-1,points,dtype=int));x=x.iloc[idx]
    values=x.iloc[:,0]
    return {"channel":channel,"points":[{"t":t.isoformat(),"v":None if pd.isna(v) else float(v)} for t,v in values.items()],"source_rows":int(total),"returned":len(x),"range":{"start":x.index[0].isoformat(),"end":x.index[-1].isoformat()}}
