from sqlalchemy import create_engine, Integer, String, Float, DateTime, Text, JSON
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Mapped, mapped_column
from app.core import settings
class Base(DeclarativeBase): pass
url=settings().database_url
engine=create_engine(url,connect_args={"check_same_thread":False} if url.startswith("sqlite") else {},pool_pre_ping=True)
Session=sessionmaker(engine,autoflush=False,autocommit=False)
class Run(Base):
    __tablename__="analysis_runs"
    id:Mapped[int]=mapped_column(Integer,primary_key=True)
    status:Mapped[str]=mapped_column(String(24),default="queued")
    processed:Mapped[int]=mapped_column(Integer,default=0)
    total:Mapped[int]=mapped_column(Integer,default=76)
    summary:Mapped[dict]=mapped_column(JSON,default=dict)
    error:Mapped[str|None]=mapped_column(Text,nullable=True)
    started:Mapped[object|None]=mapped_column(DateTime(timezone=True),nullable=True)
    completed:Mapped[object|None]=mapped_column(DateTime(timezone=True),nullable=True)
class Event(Base):
    __tablename__="detection_events"
    id:Mapped[int]=mapped_column(Integer,primary_key=True)
    run_id:Mapped[int]=mapped_column(Integer,index=True)
    channel:Mapped[str]=mapped_column(String(32),index=True)
    timestamp:Mapped[object]=mapped_column(DateTime(timezone=True),index=True)
    score:Mapped[float]=mapped_column(Float)
    severity:Mapped[str]=mapped_column(String(16))
    detector:Mapped[str]=mapped_column(String(64))
    evidence:Mapped[dict]=mapped_column(JSON,default=dict)
    annotation:Mapped[str|None]=mapped_column(String(64),nullable=True)
class Document(Base):
    __tablename__="knowledge_documents"
    id:Mapped[int]=mapped_column(Integer,primary_key=True)
    source:Mapped[str]=mapped_column(String(512),unique=True)
    content:Mapped[str]=mapped_column(Text)
def get_db():
    db=Session()
    try: yield db
    finally: db.close()
