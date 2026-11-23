from __future__ import annotations

from datetime import datetime
from sqlalchemy import create_engine, Integer, String, Float, DateTime, Text, JSON, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Mapped, mapped_column
from app.core import settings


class Base(DeclarativeBase):
    pass


cfg = settings()
engine = create_engine(
    cfg.database_url,
    connect_args={"check_same_thread": False} if cfg.database_url.startswith("sqlite") else {},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(engine, autoflush=False, autocommit=False)


class AnalysisRun(Base):
    """Superset run model preserving the M1 API/database contract."""

    __tablename__ = "analysis_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), default="analysis")
    scope: Mapped[str] = mapped_column(String(32), default="selected")
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    configuration: Mapped[dict] = mapped_column(JSON, default=dict)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    artifact_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DetectionEvent(Base):
    """Event model compatible with both the legacy M1 and final-product schema.

    Legacy code wrote ``timestamp``/``annotation`` while the final product uses
    explicit start/end/peak-time geometry, category and annotation IDs.  Keeping
    both representations prevents the validated M1 regression suite from being
    invalidated by the product-layer upgrade.
    """

    __tablename__ = "detection_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(Integer, index=True)
    channel: Mapped[str] = mapped_column(String(32), index=True)
    timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True, nullable=True)
    start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True, nullable=True)
    end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    peak_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    score: Mapped[float] = mapped_column(Float)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    detector: Mapped[str] = mapped_column(String(64), index=True)
    annotation: Mapped[str | None] = mapped_column(String(64), nullable=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    annotation_ids: Mapped[list] = mapped_column(JSON, default=list)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)

    def __init__(self, **kwargs):
        timestamp = kwargs.get("timestamp") or kwargs.get("start") or kwargs.get("peak_time")
        if timestamp is not None:
            kwargs.setdefault("timestamp", timestamp)
            kwargs.setdefault("start", timestamp)
            kwargs.setdefault("end", timestamp)
            kwargs.setdefault("peak_time", timestamp)
        annotation = kwargs.get("annotation") or kwargs.get("category")
        if annotation is not None:
            kwargs.setdefault("annotation", annotation)
            kwargs.setdefault("category", annotation)
        evidence = kwargs.get("evidence") or {}
        kwargs.setdefault("annotation_ids", list(evidence.get("annotation_ids", [])))
        super().__init__(**kwargs)


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(512), unique=True)
    content: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


# Backward-compatible names retained for the original M1/M1.1 regression suite.
Run = AnalysisRun
Event = DetectionEvent
Document = KnowledgeDocument
Session = SessionLocal


def _sqlite_add_columns(table: str, definitions: dict[str, str]) -> None:
    existing = {column["name"] for column in inspect(engine).get_columns(table)}
    with engine.begin() as connection:
        for name, ddl in definitions.items():
            if name not in existing:
                connection.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {ddl}'))


def ensure_schema() -> None:
    """Create/migrate the local SQLite schema without deleting prior run history."""

    Base.metadata.create_all(engine)
    if engine.dialect.name != "sqlite":
        return

    tables = set(inspect(engine).get_table_names())
    if "analysis_runs" in tables:
        _sqlite_add_columns("analysis_runs", {
            "kind": "VARCHAR(32) DEFAULT 'analysis'",
            "scope": "VARCHAR(32) DEFAULT 'selected'",
            "configuration": "JSON DEFAULT '{}'",
            "artifact_path": "TEXT",
        })
    if "detection_events" in tables:
        _sqlite_add_columns("detection_events", {
            "timestamp": "DATETIME",
            "start": "DATETIME",
            "end": "DATETIME",
            "peak_time": "DATETIME",
            "annotation": "VARCHAR(64)",
            "category": "VARCHAR(64)",
            "annotation_ids": "JSON DEFAULT '[]'",
        })
        # Backfill whichever geometry representation the older/newer DB lacked.
        with engine.begin() as connection:
            connection.execute(text(
                "UPDATE detection_events SET "
                "timestamp = COALESCE(timestamp, start, peak_time), "
                "start = COALESCE(start, timestamp, peak_time), "
                "end = COALESCE(end, start, timestamp, peak_time), "
                "peak_time = COALESCE(peak_time, start, timestamp), "
                "annotation = COALESCE(annotation, category), "
                "category = COALESCE(category, annotation), "
                "annotation_ids = COALESCE(annotation_ids, '[]')"
            ))
    if "knowledge_documents" in tables:
        _sqlite_add_columns("knowledge_documents", {"metadata_json": "JSON DEFAULT '{}'"})


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
