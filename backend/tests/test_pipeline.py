"""Exercise the existing API/database bridge against isolated synthetic data."""
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base, Event, Run, get_db
from app import main, pipeline
from test_experiment import write_source


def test_database_publication_and_existing_api_contract(tmp_path, monkeypatch):
    root = tmp_path / "source"
    write_source(root)
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    cfg = SimpleNamespace(dataset_dir=str(root), telemetry_store_dir=str(tmp_path / "store"),
        experiment_dir=str(tmp_path / "runs"), ingestion_row_group_size=50,
        analysis_batch_size=31, analysis_max_train_rows=100, unlabelled_policy="assume_normal")
    monkeypatch.setattr(pipeline, "settings", lambda: cfg)
    with factory() as db:
        run = Run(status="queued", total=1, processed=0)
        db.add(run)
        db.commit()
        run_id = run.id
        first = pipeline.run_all(db, run_id)
        assert first["channels_processed"] == 1
        events = db.query(Event).filter_by(run_id=run_id).all()
        assert len(events) > 0
        assert all("end" in event.evidence and "annotation_ids" in event.evidence for event in events)
        assert any("point" in event.evidence["annotation_ids"] for event in events)
        second = pipeline.run_all(db, run_id)
        assert first["detection_events"] == second["detection_events"]
        assert db.query(Event).filter_by(run_id=run_id).count() == len(events)
        assert db.get(Run, run_id).status == "completed"

    def isolated_db():
        with factory() as db:
            yield db
    main.app.dependency_overrides[get_db] = isolated_db
    try:
        client = TestClient(main.app)  # No real database lifespan or analysis launch.
        assert client.get("/api/health").json() == {"status": "ok"}
        runs = client.get("/api/analysis/runs").json()
        assert {"id", "status", "processed", "total", "summary", "error"} <= runs[0].keys()
        result = client.get(f"/api/events?run_id={run_id}&limit=1").json()
        assert len(result) == 1
        assert {"id", "channel", "timestamp", "score", "severity", "detector", "evidence", "annotation"} <= result[0].keys()
    finally:
        main.app.dependency_overrides.clear()
        engine.dispose()


def test_unlabelled_channels_do_not_become_negative_examples(tmp_path):
    from app.experiment import ExperimentConfig, run_experiment
    from app.storage import ingest_dataset
    root, store = tmp_path / "source", tmp_path / "store"
    write_source(root, target="NO")
    ingest_dataset(root, store)
    manifest = run_experiment(root, store, tmp_path / "run", config=ExperimentConfig(
        batch_size=41, max_train_rows=100, n_estimators=8, unlabelled_policy="assume_normal"))
    report = json.loads(Path(manifest["channels"]["channel_1"]["report"]).read_text())
    assert report["label_status"] == "unlabelled"
    assert report["eligible_test_rows"] == 0
    for metric in report["metrics"]["sample"].values():
        assert metric["precision"] is None
        assert metric["excluded_unknown"] == 72
    for metric in report["metrics"]["event"].values():
        assert metric["precision"] is None
        assert metric["recall"] is None
