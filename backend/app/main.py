from __future__ import annotations
from contextlib import asynccontextmanager
from pathlib import Path
import json,os
from fastapi import FastAPI,Depends,HTTPException,BackgroundTasks,Header,Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel,Field
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core import settings
from app.db import Base,engine,get_db,ensure_schema,AnalysisRun,DetectionEvent,KnowledgeDocument
from app.dataset import mission_summary,channel_catalog,channel_annotations,metadata,store_root,dataset_root
from app.service import execute_run,telemetry_sample
from app.knowledge import upsert,answer,external_research

cfg=settings()

@asynccontextmanager
async def lifespan(app:FastAPI):
    ensure_schema()
    # Seed bundled documentation into the internal evidence store. Failure is non-fatal.
    try:
        from app.db import SessionLocal
        db=SessionLocal()
        docs=(Path(__file__).resolve().parents[2]/"docs")
        for p in docs.glob("*.md"):
            upsert(db,f"docs/{p.name}",p.read_text(encoding="utf-8"),{"kind":"bundled_document"})
        db.close()
    except Exception: pass
    yield

app=FastAPI(title=cfg.app_name,version=cfg.app_version,description="Explainable spacecraft telemetry anomaly intelligence. Decision support only; no spacecraft command path.",lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=cfg.origins,allow_credentials=True,allow_methods=["GET","POST"],allow_headers=["*"])

def require_key(x_vyom_key:str|None=Header(default=None)):
    if cfg.api_key and x_vyom_key!=cfg.api_key: raise HTTPException(401,"Invalid VYOM API key")

class RunRequest(BaseModel):
    channels:list[str]|None=None
    full_mission:bool=False
    confirm_full:bool=False
    batch_rows:int=Field(default=5000,ge=500,le=100000)

class ChatRequest(BaseModel):
    question:str=Field(min_length=3,max_length=4000)
    active_context:dict=Field(default_factory=dict)

class DocRequest(BaseModel):
    source:str=Field(min_length=1,max_length=512)
    content:str=Field(min_length=1,max_length=200000)
    metadata:dict=Field(default_factory=dict)

@app.get("/api/health")
def health():
    # Preserve the original public health contract used by the M1 regression suite.
    return {"status":"ok"}

@app.get("/api/system/health")
def system_health():
    checks={}
    for key,fn in (("dataset",dataset_root),("telemetry_store",store_root)):
        try:checks[key]={"ok":True,"path":str(fn())}
        except Exception as e:checks[key]={"ok":False,"error":str(e)}
    checks["nebius"]={"configured":bool(cfg.nebius_api_key and cfg.nebius_model)}
    checks["tavily"]={"configured":bool(cfg.tavily_api_key)}
    checks["langsmith"]={"configured":bool(cfg.langsmith_api_key)}
    return {"status":"ok" if all(x.get("ok",True) for x in checks.values()) else "degraded","version":cfg.app_version,"checks":checks,"command_capability":False}

@app.get("/api/mission/summary")
def summary():return mission_summary()

@app.get("/api/channels")
def channels(target:str|None=None,subsystem:str|None=None):
    rows=channel_catalog()
    if target:rows=[x for x in rows if x["target"]==target.upper()]
    if subsystem:rows=[x for x in rows if x["subsystem"]==subsystem]
    return {"channels":rows,"count":len(rows)}

@app.get("/api/channels/{channel}/telemetry")
def telemetry(channel:str,start:str|None=None,end:str|None=None,points:int=Query(1400,ge=100,le=5000)):
    if channel not in {x["channel"] for x in channel_catalog()}:raise HTTPException(404,"Unknown channel")
    try:return telemetry_sample(channel,start,end,points)
    except Exception as e:raise HTTPException(422,f"Telemetry read failed: {type(e).__name__}: {e}")

@app.get("/api/channels/{channel}/annotations")
def annotations(channel:str):
    ann=channel_annotations(channel).copy()
    for c in ("StartTime","EndTime"):ann[c]=ann[c].astype(str)
    return {"channel":channel,"annotations":ann.to_dict("records"),"count":len(ann)}

@app.post("/api/analysis/runs",dependencies=[Depends(require_key)])
def start_run(req:RunRequest,bg:BackgroundTasks,db:Session=Depends(get_db)):
    catalog=channel_catalog();available={x["channel"] for x in catalog if x["ingested"]}
    if req.full_mission:
        if not req.confirm_full:raise HTTPException(409,"Full-mission execution requires confirm_full=true. It is compute-intensive and retrospective, not flight-qualified.")
        selected=[x["channel"] for x in catalog if x["ingested"]]
    else:
        selected=req.channels or ["channel_12","channel_41","channel_61"]
    unknown=[x for x in selected if x not in available]
    if unknown:raise HTTPException(422,f"Channels unavailable in telemetry store: {unknown}")
    r=AnalysisRun(kind="retrospective",scope="all76" if req.full_mission else "selected",status="queued",processed=0,total=len(selected),configuration={"channels":selected,"batch_rows":req.batch_rows,"protocol":"frozen VYOM 60/20/20 retrospective"})
    db.add(r);db.commit();db.refresh(r);bg.add_task(execute_run,r.id)
    return {"run_id":r.id,"status":r.status,"channels":selected,"full_mission":req.full_mission}

@app.get("/api/analysis/runs")
def runs(limit:int=Query(20,ge=1,le=100),db:Session=Depends(get_db)):
    rows=db.query(AnalysisRun).order_by(desc(AnalysisRun.id)).limit(limit).all()
    return [{"id":r.id,"kind":r.kind,"scope":r.scope,"status":r.status,"processed":r.processed,"total":r.total,"summary":r.summary,"configuration":r.configuration,"artifact_path":r.artifact_path,"error":r.error,"started":r.started.isoformat() if r.started else None,"completed":r.completed.isoformat() if r.completed else None} for r in rows]

@app.get("/api/events")
def events(run_id:int|None=None,channel:str|None=None,severity:str|None=None,detector:str|None=None,limit:int=Query(250,ge=1,le=2000),db:Session=Depends(get_db)):
    q=db.query(DetectionEvent)
    if run_id is not None:q=q.filter(DetectionEvent.run_id==run_id)
    if channel:q=q.filter(DetectionEvent.channel==channel)
    if severity:q=q.filter(DetectionEvent.severity==severity)
    if detector:q=q.filter(DetectionEvent.detector==detector)
    rows=q.order_by(desc(DetectionEvent.start),desc(DetectionEvent.timestamp)).limit(limit).all()
    result=[]
    for e in rows:
        start=e.start or e.timestamp or e.peak_time
        end=e.end or start
        peak=e.peak_time or start
        result.append({"id":e.id,"run_id":e.run_id,"channel":e.channel,
            "timestamp":(e.timestamp or start).isoformat() if (e.timestamp or start) else None,
            "start":start.isoformat() if start else None,"end":end.isoformat() if end else None,
            "peak_time":peak.isoformat() if peak else None,"score":e.score,"severity":e.severity,
            "detector":e.detector,"annotation":e.annotation or e.category,"category":e.category or e.annotation,
            "annotation_ids":e.annotation_ids or [],"evidence":e.evidence or {}})
    return result

@app.get("/api/reports")
def reports():
    root=cfg.resolve(cfg.artifact_dir);result=[]
    if root.exists():
        for p in sorted(root.rglob("report.json"),key=lambda x:x.stat().st_mtime,reverse=True)[:250]:
            try:d=json.loads(p.read_text(encoding="utf-8"));result.append({"path":str(p),"channel":d.get("channel"),"status":d.get("status"),"events":d.get("events"),"metrics":d.get("event_metrics_nominal_complement"),"resources":d.get("resources")})
            except Exception:pass
    return {"reports":result,"count":len(result)}

@app.get("/api/system/evidence")
def evidence():
    m=metadata();return {"dataset":{"channels":len(m["channels"]),"labels":len(m["labels"]),"anomaly_types":len(m["anomaly_types"]),"telecommands":len(m["telecommands"])},"protocol":{"split":"60/20/20 chronological by observation count","calibration":"99th percentile validation score, higher order statistic, minimum 3","target_no":"context only; never supervised negative","metric":"VYOM one-to-one closed-overlap event metric; not ESA official leaderboard metric"},"limitations":["Retrospective evaluation is not external blind validation.","Unannotated periods follow the benchmark nominal-complement convention; physical normality is not independently guaranteed.","VYOM is research decision support and is not flight-qualified."]}

@app.post("/api/knowledge/ingest",dependencies=[Depends(require_key)])
def ingest_doc(x:DocRequest,db:Session=Depends(get_db)):return {"document_id":upsert(db,x.source,x.content,x.metadata)}

@app.post("/api/chat")
def chat(x:ChatRequest,db:Session=Depends(get_db)):
    try:return answer(db,x.question,x.active_context)
    except Exception as e:raise HTTPException(502,f"Assistant provider error: {type(e).__name__}: {e}")

@app.get("/api/research/search")
def research(query:str=Query(min_length=3,max_length=500)):
    try:return external_research(query)
    except Exception as e:raise HTTPException(502,f"External research provider error: {type(e).__name__}: {e}")
