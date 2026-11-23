"""Existing dashboard/database contract backed by the offline experiment engine."""
from datetime import datetime, timezone
import json
from pathlib import Path

from app.core import settings
from app.db import Run, Event
from app.experiment import ExperimentConfig, run_experiment
from app.storage import ingest_dataset
from app.telemetry import resolve_dataset, metadata


def run_all(db, run_id):
    cfg = settings()
    root = resolve_dataset(cfg.dataset_dir)
    channels = metadata(root)["channels"].Channel.astype(str).tolist()
    run = db.get(Run, run_id)
    run.status = "running"
    run.started = datetime.now(timezone.utc)
    run.total = len(channels)
    db.commit()
    store = Path(cfg.telemetry_store_dir).resolve()
    output = Path(cfg.experiment_dir).resolve() / f"api_run_{run_id}"
    ingest_dataset(root, store, channels=channels, row_group_size=cfg.ingestion_row_group_size)
    completed = set()
    event_count = 0

    def publish_channel(channel, report):
        nonlocal event_count
        # One transaction per channel makes database publication idempotent on resume.
        db.query(Event).filter_by(run_id=run_id, channel=channel).delete(synchronize_session=False)
        pending = []
        channel_events = 0
        with Path(report["artifacts"]["events"]).open(encoding="utf-8") as stream:
            for line in stream:
                event = json.loads(line)
                if event["detector"] not in {"combined", "timestamp_gap"}:
                    continue
                score = float(event["peak_score"])
                pending.append(Event(run_id=run_id, channel=channel,
                    timestamp=datetime.fromisoformat(event["start"]), score=score,
                    severity="critical" if score >= 2 else "high" if score >= 1.5 else "medium",
                    detector=event["detector"], evidence={**event["evidence"],
                        "start": event["start"], "end": event["end"],
                        "duration_seconds": event["duration_seconds"],
                        "annotation_ids": event["annotation_ids"],
                        "experiment_report": str(output / channel / "report.json")},
                    annotation=";".join(event["categories"]) or None))
                channel_events += 1
                if len(pending) >= 1000:
                    db.add_all(pending)
                    db.flush()
                    pending.clear()
        if pending:
            db.add_all(pending)
        completed.add(channel)
        event_count += channel_events
        run.processed = len(completed)
        run.summary = {"channels_processed": len(completed), "detection_events": event_count,
                       "experiment_manifest": str(output / "manifest.json")}
        db.commit()

    manifest = run_experiment(root, store, output, channels=channels,
        config=ExperimentConfig(batch_size=cfg.analysis_batch_size, max_train_rows=cfg.analysis_max_train_rows,
                                unlabelled_policy=cfg.unlabelled_policy), progress=publish_channel)
    run.status = "completed"
    run.completed = datetime.now(timezone.utc)
    run.summary = {"dataset": "ESA Mission-1", "channels_available": len(channels),
        "channels_processed": len(completed), "detection_events": event_count,
        "annotation_categories": ["Anomaly", "Rare Event", "Communication Gap"],
        "experiment_manifest": str(output / "manifest.json"), "status": manifest["status"],
        "metrics_note": "Chronological holdout metrics are in the experiment manifest; inspect label policy and per-channel support."}
    db.commit()
    return run.summary
