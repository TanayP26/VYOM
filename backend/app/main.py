from contextlib import asynccontextmanager
from fastapi import FastAPI,Depends,HTTPException,BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel,Field
from sqlalchemy.orm import Session
from sqlalchemy import desc
from app.core import settings
from app.db import Base,engine,Session as SessionFactory,Run,Event,Document,get_db
from app.pipeline import run_all
from app.rag import ingest,answer,research

@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine);yield
app=FastAPI(title="VYOM Mission Intelligence",version="1.0.0",lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=settings().origins,allow_credentials=True,allow_methods=["GET","POST"],allow_headers=["*"])
def background(run_id):
    db=SessionFactory()
    try:run_all(db,run_id)
    except Exception as e:
        db.rollback()
        r=db.get(Run,run_id)
        if r:r.status="failed";r.error=f"{type(e).__name__}: {e}"[:2000];db.commit()
    finally:db.close()
class Chat(BaseModel):question:str=Field(min_length=3,max_length=4000)
class Doc(BaseModel):source:str=Field(min_length=1,max_length=512);content:str=Field(min_length=1,max_length=100000)
@app.get("/api/health")
def health():return {"status":"ok"}
@app.post("/api/analysis/runs")
def start(bg:BackgroundTasks,db:Session=Depends(get_db)):
    r=Run(status="queued",total=76,processed=0);db.add(r);db.commit();db.refresh(r);bg.add_task(background,r.id)
    return {"run_id":r.id,"status":r.status,"channels":76}
@app.get("/api/analysis/runs")
def runs(db:Session=Depends(get_db)):
    return [{"id":r.id,"status":r.status,"processed":r.processed,"total":r.total,"summary":r.summary,"error":r.error}
      for r in db.query(Run).order_by(desc(Run.id)).limit(20)]
@app.get("/api/events")
def events(run_id:int|None=None,channel:str|None=None,limit:int=100,db:Session=Depends(get_db)):
    q=db.query(Event)
    if run_id is not None:q=q.filter(Event.run_id==run_id)
    if channel:q=q.filter(Event.channel==channel)
    return [{"id":e.id,"run_id":e.run_id,"channel":e.channel,"timestamp":e.timestamp.isoformat(),
      "score":e.score,"severity":e.severity,"detector":e.detector,"evidence":e.evidence,
      "annotation":e.annotation} for e in q.order_by(desc(Event.score)).limit(min(max(limit,1),1000))]
@app.post("/api/knowledge/ingest")
def add_doc(x:Doc,db:Session=Depends(get_db)):return {"document_id":ingest(db,x.source,x.content)}
@app.post("/api/chat")
def chat(x:Chat,db:Session=Depends(get_db)):
    try:return answer(db,x.question)
    except Exception as e:raise HTTPException(502,f"Chat provider error: {type(e).__name__}")
@app.get("/api/research/search")
def search(query:str):
    if len(query.strip())<3:raise HTTPException(400,"Query too short")
    return {"results":research(query),"source":"External research, not telemetry evidence"}
