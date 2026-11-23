"""Read the five existing Parquet channels and profile their sampling regimes."""
import argparse
import json
import logging
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.artifacts import ResourceMonitor, atomic_json, configure_logging, file_sha256, utc_now
from app.cadence import SamplingRegimeTracker, training_cadence
from app.storage import iter_channel_batches


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, default=Path("../artifacts/telemetry"))
    parser.add_argument("--output", type=Path, default=Path("../artifacts/milestone11/regimes"))
    args = parser.parse_args()
    configure_logging()
    args.output.mkdir(parents=True, exist_ok=True)
    store_manifest = json.loads((args.store / "manifest.json").read_text())
    report = {"created_at": utc_now(), "status": "running", "channels": {},
              "scope": "sampling-only full-time scans of five previously ingested channels; no model benchmark",
              "source_store_manifest_sha256": file_sha256(args.store / "manifest.json")}
    with ResourceMonitor() as total:
        for channel in ("channel_1", "channel_12", "channel_41", "channel_61", "channel_74"):
            tracker = None
            gap_path = args.output / f"{channel}_gaps.jsonl"
            with ResourceMonitor() as monitor, gap_path.open("w", encoding="utf-8") as stream:
                for batch in iter_channel_batches(args.store, channel, batch_size=250000):
                    if tracker is None:
                        tracker = SamplingRegimeTracker(training_cadence(batch.index[:10001]))
                    tracker.transform(batch.index)
                    for gap in tracker.drain_gaps():
                        stream.write(json.dumps(gap) + "\n")
                    if tracker.rows_seen % 5000000 < len(batch):
                        logging.info("regime_profile channel=%s rows=%d", channel, tracker.rows_seen)
                for gap in tracker.finish():
                    stream.write(json.dumps(gap) + "\n")
            entry = {"channel": channel, "status": "completed", "rows": tracker.rows_seen,
                 "source_parquet_sha256": store_manifest["channels"][channel]["file_sha256"],
                 "tracker": tracker.metadata(), "regimes": tracker.regimes(),
                 "resources": monitor.measurements, "gap_candidates": str(gap_path.resolve())}
            report["channels"][channel] = entry
            atomic_json(args.output / f"{channel}_profile.json", entry)
            atomic_json(args.output / "sampling_regimes.json", report)
            logging.info("regime_profile completed channel=%s regimes=%d resources=%s", channel, len(entry["regimes"]), monitor.measurements)
    report.update(status="completed", completed_at=utc_now(), resources=total.measurements)
    atomic_json(args.output / "sampling_regimes.json", report)
    print(json.dumps({"status": report["status"], "resources": report["resources"]}))


if __name__ == "__main__":
    main()
