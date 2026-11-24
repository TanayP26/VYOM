import json
from pathlib import Path

from app.product_streaming import _extract_incidents, _product_summary


def test_incident_projection_filters_detector_evidence(tmp_path: Path):
    journal = tmp_path / "journal"
    journal.mkdir()
    rows = [
        {"model":"temporal_point","channel":"channel_12","start":"2026-01-01T00:00:00+00:00",
         "end":"2026-01-01T00:00:00+00:00","peak_time":"2026-01-01T00:00:00+00:00",
         "peak_score":4.0,"annotation_ids":[],"categories":[]},
        {"model":"combined","channel":"channel_12","start":"2026-01-01T00:00:00+00:00",
         "end":"2026-01-01T00:00:00+00:00","peak_time":"2026-01-01T00:00:00+00:00",
         "peak_score":1.2,"annotation_ids":["A1"],"categories":["Anomaly"]},
        {"model":"adaptive_gap","channel":"channel_12","start":"2026-01-02T00:00:01+00:00",
         "end":"2026-01-02T00:01:59+00:00","right_observed":"2026-01-02T00:02:00+00:00",
         "peak_score":4.0,"annotation_ids":[],"categories":[]},
    ]
    (journal/"generation-00000001-correlated_events.json").write_text(json.dumps(rows), encoding="utf-8")
    incidents = _extract_incidents(tmp_path)
    assert [x["detector"] for x in incidents] == ["combined", "timestamp_gap"]
    assert incidents[0]["annotation_ids"] == ["A1"]
    assert all(x["evidence"]["source"] == "app.streaming_benchmark" for x in incidents)


def test_product_summary_keeps_evidence_separate_from_incidents(tmp_path: Path):
    report = {
        "status":"completed","scope":"B","split":{"test_rows":10},
        "models":{
            "combined":{"event":{"assumed_normal":{"tp":1,"fp":2},"supported_ground_truth":{"recall":1.0},
                                  "burden":{"predicted_events":3}},
                        "sample":{"assumed_normal":{"tp":1},"supported_ground_truth":{"labelled_positive_recall":1.0},
                                  "burden":{"flagged_samples":4}}},
            "temporal_point":{"event":{"burden":{"predicted_events":7}}},
        },
        "communication_gaps":{"event":{"burden":{"predicted_events":1}}},
        "regimes":[],"unsupported_comparators":{},"comparator_scored_rows":{},
        "history_truncation_rows":0,"post_gap_test_rows":0,
    }
    incidents = [
        {"detector":"combined"},
        {"detector":"combined"},
        {"detector":"timestamp_gap"},
    ]
    summary = _product_summary("channel_12", tmp_path, report, incidents)
    assert summary["incidents"] == 3
    assert summary["combined_events"] == 2
    assert summary["timestamp_gap_candidates"] == 1
    assert summary["detector_evidence"]["combined"] == 3
    assert summary["detector_evidence"]["temporal_point"] == 7


def test_product_summary_marks_combined_abstention(tmp_path: Path):
    report={"status":"completed_with_unsupported_comparators","scope":"B","split":{"test_rows":10},
      "models":{"temporal_point":{"event":{"burden":{"predicted_events":3}}}},
      "communication_gaps":{"event":{"burden":{"predicted_events":0}}},
      "unsupported_comparators":{"combined":{"status":"unsupported","reason":"history ceiling"}},
      "comparator_scored_rows":{"combined":0,"temporal_point":10},"regimes":[],
      "history_truncation_rows":0,"post_gap_test_rows":0,"history_compatibility":{"status":"unsupported_resource_ceiling"}}
    summary=_product_summary("channel_12",tmp_path,report,[])
    assert summary["status"]=="completed_with_abstention"
    assert summary["operator_incident_status"]=="abstained"
    assert summary["operator_incident_reason"]=="history ceiling"
