"""Read-only forensic diagnosis of preserved Milestone 1 pilot artifacts.

Run from repository root with backend/.venv/Scripts/python.exe.
Only artifacts/milestone11/investigation is written. No fitting or tuning occurs.
"""
import argparse
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.artifacts import atomic_json, file_sha256, ResourceMonitor, utc_now
from app.detectors import IsolationForestDetector


def quantiles(values):
    series = pd.Series(values).replace([np.inf, -np.inf], np.nan).dropna()
    return {str(q): float(v) for q, v in series.quantile([0, .25, .5, .75, .9, .95, .99, 1]).items()} if len(series) else {}


def records(frame):
    return json.loads(frame.reset_index().to_json(orient="records", date_format="iso", date_unit="ns"))


def investigate(folder, channel):
    path = ROOT / "artifacts" / folder / channel
    report = json.loads((path / "report.json").read_text())
    features = pd.read_parquet(path / "features_0.parquet").set_index("timestamp")
    predictions = pd.read_parquet(path / "predictions.parquet").set_index("timestamp")
    selected = features.loc[predictions.index]
    positive = predictions.target == 1
    unannotated = predictions.target == 0
    zero = selected.rolling_mad == 0
    flags = predictions.statistical_flag
    iso = IsolationForestDetector.load(path / "isolation_forest_0.joblib")
    train = features.iloc[:report["selection"]["train_rows"]]
    train_scores = iso.score(train)
    events = [json.loads(line) for line in (path / "events.jsonl").read_text().splitlines()]
    combined = [event for event in events if event["detector"] == "combined"]
    event_lengths = pd.Series([event["sample_count"] for event in combined], dtype=int)
    truth_path = ROOT / "data/esa_adb/mission1/ESA-Mission1"
    labels = pd.read_csv(truth_path / "labels.csv")
    types = pd.read_csv(truth_path / "anomaly_types.csv")
    labels = labels.merge(types, on="ID", validate="many_to_one")
    labels.StartTime = pd.to_datetime(labels.StartTime, utc=True)
    labels.EndTime = pd.to_datetime(labels.EndTime, utc=True)
    labels = labels[(labels.Channel == channel) & (labels.EndTime >= predictions.index[0]) & (labels.StartTime <= predictions.index[-1])]
    data = {
        "channel": channel, "source_artifact_directory": str(path),
        "source_hashes": {p.name: file_sha256(p) for p in path.iterdir() if p.is_file()},
        "rows": {"train": len(train), "test": len(selected), "annotated_positive": int(positive.sum()),
                 "assumed_normal": int(unannotated.sum()), "short_history_invalid": int((selected.feature_valid == 0).sum())},
        "fixed_thresholds": {"statistical": 6.0, "iforest": iso.metadata()["threshold"]},
        "zero_mad": {"test_rows": int(zero.sum()), "flagged_rows": int((zero & flags).sum()),
                     "unannotated_rows": int((zero & unannotated).sum()),
                     "unannotated_flagged_rows": int((zero & unannotated & flags).sum()),
                     "flagged_zero_mad_deviation_quantiles": quantiles((selected.value - selected.rolling_median).abs()[zero & flags]),
                     "flagged_zero_mad_score_quantiles": quantiles(selected.robust_score[zero & flags])},
        "detector_contributions": {"statistical": int(flags.sum()), "iforest": int(predictions.isolation_forest_flag.sum()),
                                  "combined": int(predictions.combined_flag.sum()),
                                  "iforest_unique": int((predictions.isolation_forest_flag & ~flags).sum())},
        "signal_quantization": {"training_unique_values": int(train.value.nunique()),
                                "training_nonzero_absolute_change_quantiles": quantiles(train.value_change.abs()[train.value_change != 0]),
                                "training_mad_zero_fraction": float((train.rolling_mad == 0).mean())},
        "score_distributions": {"train_statistical": quantiles(train.robust_score),
                                "test_statistical": quantiles(selected.robust_score),
                                "train_iforest_valid_only": quantiles(train_scores.iforest_score),
                                "test_iforest_valid_only": quantiles(iso.score(selected).iforest_score)},
        "events": {"combined_count": len(combined), "single_sample_events": int((event_lengths == 1).sum()),
                   "sample_count_quantiles": quantiles(event_lengths),
                   "duration_seconds_quantiles": quantiles([e["duration_seconds"] for e in combined]),
                   "events_overlapping_truth": sum(bool(e["annotation_ids"]) for e in combined),
                   "metrics": report["metrics"]["event"]["combined"]},
        "truth": records(labels), "missed_positive_reasons": {
            "short_history_invalid": int((positive & (selected.feature_valid == 0)).sum()),
            "valid_score_at_or_below_six": int((positive & (selected.feature_valid == 1) & (selected.robust_score <= 6)).sum()),
            "unused_long_scale_above_six": int((positive & ~flags & (selected.robust_score_scale_4 > 6)).sum()),
            "positive_rolling_median_equals_value": int((positive & (selected.rolling_median == selected.value)).sum())},
        "annotation_neighbourhoods": [],
    }
    for label in labels.to_dict("records"):
        point = label["StartTime"] == label["EndTime"]
        location = int(np.argmin(np.abs((features.index - label["StartTime"]).total_seconds())))
        nearby = features.iloc[max(0, location - 5):min(len(features), location + 12)].join(predictions, rsuffix="_prediction")
        data["annotation_neighbourhoods"].append({"id": label["ID"], "is_point": point,
             "nearest_row_position": location, "nearest_timestamp": features.index[location].isoformat(),
             "timestamp_offset_seconds": float((features.index[location] - label["StartTime"]).total_seconds()),
             "records": records(nearby)})
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/milestone11/investigation/baseline_forensics.json")
    destination = parser.parse_args().output
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        print(json.dumps({"status": "existing_report_preserved", "output": str(destination),
                          "note": "Use --output with a new filename to repeat the investigation."}))
        return
    with ResourceMonitor() as monitor:
        result = {"created_at": utc_now(), "purpose": "Diagnosis only; no model fitting, tuning or old-artifact mutation",
                  "cases": [investigate("pilot_annotation_interval", "channel_12"),
                            investigate("pilot_annotation_point", "channel_61")]}
    result["resources"] = monitor.measurements
    atomic_json(destination, result)
    print(json.dumps({"output": str(destination), "resources": monitor.measurements}))


if __name__ == "__main__":
    main()
