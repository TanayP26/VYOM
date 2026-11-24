from __future__ import annotations

from pathlib import Path
import json

from app.dataset import channel_annotations, channel_parquet, metadata
from app.storage import atomic_json
from app.streaming_benchmark import run_channel as run_m13_channel


def _labelled_channel(channel: str) -> bool:
    row = metadata()["channels"].set_index("Channel").loc[channel]
    return str(row["Target"]).upper() == "YES"


def _load_correlated_events(output: Path) -> list[dict]:
    journal = output / "journal"
    events: list[dict] = []
    for path in sorted(journal.glob("generation-*-correlated_events.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, list):
            raise ValueError(f"Unexpected correlated-event artifact: {path}")
        events.extend(value)
    return events


def _display_severity(model: str, score: float) -> str:
    if model == "adaptive_gap":
        if score >= 10:
            return "critical"
        if score >= 5:
            return "high"
        return "medium"
    if score >= 4:
        return "critical"
    if score >= 2:
        return "high"
    return "medium"


def _incident(event: dict) -> dict:
    model = str(event.get("model", ""))
    if model not in {"combined", "adaptive_gap"}:
        raise ValueError(f"Non-incident model supplied: {model}")

    start = event["start"]
    end = event["end"]
    peak_time = (
        event.get("peak_time")
        or event.get("right_observed")
        or event.get("resolved_at")
        or end
    )
    score = float(event.get("peak_score", event.get("score", 1.0)))
    evidence = dict(event.get("evidence") or {})
    evidence.update({
        "m13_model": model,
        "evidence_role": "operator_incident",
        "severity_semantics": "display triage derived from detector score; not spacecraft consequence severity",
        "source": "app.streaming_benchmark",
    })
    if "count" in event:
        evidence["flagged_observations"] = int(event["count"])
    if "duration_seconds" in event:
        evidence["duration_seconds"] = float(event["duration_seconds"])

    return {
        "channel": event.get("channel"),
        "detector": "timestamp_gap" if model == "adaptive_gap" else "combined",
        "start": start,
        "end": end,
        "peak_time": peak_time,
        "peak_score": score,
        "severity": _display_severity(model, score),
        "annotation_ids": list(event.get("annotation_ids") or []),
        "categories": list(event.get("categories") or []),
        "evidence": evidence,
    }


def _extract_incidents(output: Path) -> list[dict]:
    result = []
    seen = set()
    for event in _load_correlated_events(output):
        model = str(event.get("model", ""))
        if model not in {"combined", "adaptive_gap"}:
            continue
        incident = _incident(event)
        key = (
            incident["detector"],
            incident["channel"],
            incident["start"],
            incident["end"],
            incident["peak_time"],
        )
        if key not in seen:
            seen.add(key)
            result.append(incident)
    result.sort(key=lambda e: (e["start"], e["detector"], e["end"]))
    return result


def _predicted_events(model_result: dict | None) -> int:
    if not model_result:
        return 0
    return int(
        (((model_result.get("event") or {}).get("burden") or {}).get("predicted_events"))
        or 0
    )


def _product_summary(channel: str, output: Path, report: dict, incidents: list[dict]) -> dict:
    models = report.get("models") or {}
    combined = models.get("combined") or {}
    gap = report.get("communication_gaps") or {}

    detector_evidence = {
        name: _predicted_events(value)
        for name, value in models.items()
    }
    detector_evidence["adaptive_gap"] = _predicted_events(gap)

    combined_event = combined.get("event") or {}
    combined_sample = combined.get("sample") or {}
    execution_path = output / "execution.json"
    execution = (
        json.loads(execution_path.read_text(encoding="utf-8"))
        if execution_path.is_file()
        else {}
    )

    combined_count = sum(e["detector"] == "combined" for e in incidents)
    gap_count = sum(e["detector"] == "timestamp_gap" for e in incidents)
    unsupported = report.get("unsupported_comparators") or {}
    combined_available = "combined" not in unsupported
    operator_status = "available" if combined_available else "abstained"

    return {
        "channel": channel,
        "status": report.get("status") if combined_available else "completed_with_abstention",
        "operator_incident_status": operator_status,
        "operator_incident_reason": None if combined_available else (unsupported.get("combined") or {}).get("reason"),
        "engine": "m1.3_streaming_benchmark",
        "scope": report.get("scope"),
        "split": report.get("split"),
        "events": len(incidents),
        "incidents": len(incidents),
        "combined_events": combined_count,
        "timestamp_gap_candidates": gap_count,
        "detector_evidence": detector_evidence,
        "event_metrics_nominal_complement": combined_event.get("assumed_normal"),
        "event_metrics_supported_ground_truth": combined_event.get("supported_ground_truth"),
        "event_burden": combined_event.get("burden"),
        "sample_metrics_nominal_complement": combined_sample.get("assumed_normal"),
        "sample_metrics_supported_ground_truth": combined_sample.get("supported_ground_truth"),
        "sample_burden": combined_sample.get("burden"),
        "communication_gap": gap,
        "regimes": report.get("regimes"),
        "unsupported_comparators": report.get("unsupported_comparators"),
        "comparator_scored_rows": report.get("comparator_scored_rows"),
        "history_truncation_rows": report.get("history_truncation_rows"),
        "post_gap_test_rows": report.get("post_gap_test_rows"),
        "history_compatibility": report.get("history_compatibility"),
        "resources": execution.get("resources") or {},
        "scientific_report": str((output / "report.json").resolve()),
        "execution_report": str(execution_path.resolve()) if execution_path.is_file() else None,
        "scientific_note": (
            "M1.3 retrospective held-out evaluation under the frozen declared procedure; "
            "not external blind validation and not an ESA official leaderboard metric."
        ),
    }


def run_channel(channel: str, output: Path, batch_rows: int = 5000, **_) -> tuple[dict, list[dict]]:
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    parquet = channel_parquet(channel)

    report = run_m13_channel(
        parquet,
        output,
        channel,
        annotation_provider=lambda: channel_annotations(channel).copy(),
        labelled_channel=_labelled_channel(channel),
        batch_size=int(batch_rows),
        scope="B",
        train_fraction=.6,
        validation_fraction=.2,
    )

    incidents = _extract_incidents(output)
    summary = _product_summary(channel, output, report, incidents)

    atomic_json(output / "product_summary.json", summary)
    with (output / "incident_events.jsonl").open("w", encoding="utf-8") as stream:
        for event in incidents:
            stream.write(json.dumps(event, allow_nan=False, default=str) + "\n")

    return summary, incidents
