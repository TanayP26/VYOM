"""Render Milestone 1.1 Markdown reports from completed measured artifacts."""
from collections import defaultdict
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/"artifacts/milestone11"
DOCS=ROOT/"docs"
RUN=BASE/"comparison_final"


def read(path):
    return json.loads(path.read_text())


def f(value,places=4):
    return "—" if value is None else f"{value:.{places}f}"


def save(name,lines):
    (DOCS/name).write_text("\n".join(lines)+"\n",encoding="utf-8")


def main():
    manifest=read(RUN/"manifest.json")
    assert manifest["status"]=="completed"
    reports={case:read(Path(entry["report"])) for case,entry in manifest["cases"].items()}
    rows=[]
    for case,report in reports.items():
        for model,m in report["models"].items():
            rows.append({"case":case,"model":model,"sample":m["sample"]["assumed_normal"],
                         "event":m["event"]["assumed_normal"],"burden":m["event"]["burden"],
                         "resources":m["resources"]})
    (BASE/"reports").mkdir(exist_ok=True)
    (BASE/"reports/detection_comparison.json").write_text(json.dumps(rows,indent=2),encoding="utf-8")
    lines=["# Detection comparison — measured Milestone 1.1 results","",
       "All candidates within a case use identical chronological timestamps. Primary split: 60/20/20. Secondary split: 50/20/30 preserves the original 6000-row holdout. Splits are reported separately; no winner or hyperparameter was chosen using final labels.","",
       "Precision/F1/false alarms below use the official nominal-complement convention **as an explicit assumption** on labelled channels. Annotation-supported recall and label-independent burden are separately available in every case report. A dash means unavailable, including recall/F1 when the final partition has no positive truth. These are development-exposed, selection-biased diagnostic windows, not a blind full benchmark.","",
       "## Same original holdouts: historical before/after","",
       "| Diagnostic | Model | Sample precision | Sample recall | Sample F1 | Event precision | Event recall | Event F1 | Unmatched events |",
       "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for case,old_folder,channel in [("interval_channel_12/50_20_30","pilot_annotation_interval","channel_12"),
                                   ("point_channel_61/50_20_30","pilot_annotation_point","channel_61")]:
        old=read(ROOT/"artifacts"/old_folder/channel/"report.json")
        s,e=old["metrics"]["sample"]["combined"],old["metrics"]["event"]["combined"]
        lines.append(f"| {channel} | M1 combined | {f(s['precision'])} | {f(s['recall'])} | {f(s['f1'])} | {f(e['precision'])} | {f(e['recall'])} | {f(e['f1'])} | {e['fp']} |")
        for name in ("robust_statistical","isolation_forest","temporal_point","temporal_interval","improved_temporal","combined"):
            m=reports[case]["models"][name];s=m["sample"]["assumed_normal"];e=m["event"]["assumed_normal"]
            lines.append(f"| {channel} | M1.1 {name} | {f(s['precision'])} | {f(s['recall'])} | {f(s['f1'])} | {f(e['precision'])} | {f(e['recall'])} | {f(e['f1'])} | {e['fp']} |")
    lines += ["", "The historical M1 model used the whole 70% prefix for training. M1.1 divides that prefix into 50% training and 20% validation. Its baseline sample flags remain directly comparable; cadence-aware grouping can change event counts. The contemporary candidate tables below are the fair comparisons with identical fitting/calibration partitions. Do not attribute every historical difference solely to the detector.","",
       "On the interval diagnostic, the interval-specific strategy detects sustained behaviour with fewer events than the general point+interval union. On prefix windows, adding IF sometimes increases burden; channel74's combined candidate emits 262 events versus 97 for improved temporal and 2 for the statistical candidate on the 50/20/30 split. No model is declared universally best.","",
       "The channel61 point lies in validation under 60/20/20, so its primary final partition has no point event and no supported recall estimate. The predeclared 50/20/30 regression split places it in the same final holdout as M1. Both outcomes are retained.","",
       "## Every measured comparison","",
       "S-P/R/F1 are sample metrics; E-P/R/F1 are strict one-to-one event metrics. Runtime sums measured dependent processing stages (shared features reused); memory is sampled absolute process RSS, not isolated per-model allocation. Evaluation and artifact writing are outside per-model stage times; full experiment time includes them. PCA includes validation scoring. No GPU was used.",""]
    for case,report in reports.items():
        lines += [f"### {case}","",f"Final range: `{report['split']['test_start']}` through `{report['split']['test_end']}`; {report['split']['test_rows']:,} rows.","",
           "| Model | S-P | S-R | S-F1 | E-P | E-R | E-F1 | Assumed FA/day | Events | Seconds | Peak RSS MiB |",
           "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for name,m in report["models"].items():
            s=m["sample"]["assumed_normal"];e=m["event"]["assumed_normal"];b=m["event"]["burden"];r=m["resources"]
            lines.append(f"| {name} | {f(s['precision'])} | {f(s['recall'])} | {f(s['f1'])} | {f(e['precision'])} | {f(e['recall'])} | {f(e['f1'])} | {f(e['false_alarms_per_day'])} | {b['predicted_events']} | {f(r['measured_processing_seconds'],3)} | {f(r['peak_sampled_process_rss_mib'],2)} |")
        lines.append("")
    lines += ["PCA is an additional controlled comparison on 2000 common 30-second bins from channels41/74, which share the same anonymous physical-unit token. They belong to different subsystems; engineering correlation is not asserted. Every comparator in each PCA case uses the same aligned timestamps. Causal bins exclude their right endpoint; no interpolation/backfill occurs. This alignment is not compared as though it were the unresampled20,000-row task. These aligned prefix tests contain no positive truth, so PCA anomaly recall remains unestablished.","",
      "Random Forest was skipped: the selected chronological training windows have no positive value-annotation events, and no independently confirmed normal training examples were supplied. Nominal-complement assumptions were not silently converted into supervised labels.","",
      "[Machine-readable comparison](../artifacts/milestone11/reports/detection_comparison.json) · [Run manifest](../artifacts/milestone11/comparison_final/manifest.json)"]
    save("M11_DETECTION_COMPARISON.md",lines)

    regimes=read(BASE/"regimes/sampling_regimes.json")
    lines=["# Sampling regime report","", "A sampling-only scan covered all 59,926,812 timestamps in the five existing Parquet channels. No full 76-channel anomaly benchmark was run. UTC source timestamps and M1 profile artifacts remain unchanged.","",
       "A persistent change requires 8 consecutive deltas within 5% of the first candidate delta and outside 5% of the current cadence. Cadence changes causally at confirmation; `effective_start` is retrospective descriptive metadata only. It is never used to rewrite past features or tolerances. Isolated deltas greater than 3 expected cadences remain gap candidates, with an unknown cause. Pending transitions are resolved on return/inconsistency; terminal pending intervals are explicitly unconfirmed.","",
       "| Channel | Rows | Confirmed segments | Distinct segment cadences | Resolved gap candidates | Seconds | Peak RSS MiB |",
       "|---|---:|---:|---|---:|---:|---:|"]
    detail=["# All confirmed sampling segments","", "Durations use confirmed starts; effective starts and confirmation lags expose detection latency. Segment boundaries are inferred timing hypotheses, not spacecraft operational truth.",""]
    for channel,entry in regimes["channels"].items():
        values=sorted({r["cadence_seconds"] for r in entry["regimes"]})
        by_cadence=defaultdict(float)
        for r in entry["regimes"]:by_cadence[r["cadence_seconds"]]+=r["duration_seconds"]
        m=entry["resources"]
        lines.append(f"| {channel} | {entry['rows']:,} | {len(entry['regimes'])} | {', '.join(f'{v:g}s' for v in values)} | {entry['tracker']['resolved_gap_candidates']:,} | {f(m['wall_seconds'],3)} | {f(m['peak_sampled_rss_mib'],2)} |")
        detail += [f"## {channel}","","| Segment | Confirmed start UTC | End UTC | Effective start UTC | Cadence seconds | Duration days | Confirmation lag seconds | Observations |",
                  "|---:|---|---|---|---:|---:|---:|---:|"]
        for r in entry["regimes"]:
            detail.append(f"| {r['regime_id']} | {r['start']} | {r['end']} | {r['effective_start']} | {r['cadence_seconds']:g} | {r['duration_seconds']/86400:.6f} | {r['confirmation_lag_seconds']:.3f} | {r['observations']:,} |")
        detail.append("")
    lines += ["", f"Whole scan: **{regimes['resources']['wall_seconds']:.3f} seconds**, sampled peak RSS **{regimes['resources']['peak_sampled_rss_mib']:.3f} MiB**. The estimator stores at most one batch, pending confirmation observations and a capped segment list. Normal runs use vectorized updates; irregular portions require more work.","",
      "## Duration by confirmed cadence","","| Channel | Cadence seconds | Total segment duration days |","|---|---:|---:|"]
    for channel,entry in regimes["channels"].items():
        distribution=defaultdict(float)
        for r in entry["regimes"]:distribution[r["cadence_seconds"]]+=r["duration_seconds"]
        for cadence,duration in sorted(distribution.items()):lines.append(f"| {channel} | {cadence:g} | {duration/86400:.6f} |")
    lines += ["", "All 601 segment start/end times and durations: [detailed segment report](../artifacts/milestone11/reports/sampling_regime_details.md). Per-channel profile JSON and gap candidate JSONL are in [the sampling manifest](../artifacts/milestone11/regimes/sampling_regimes.json).", "",
      "Expected sampling changes are not automatically communication failures. An 8-observation confirmation delay is deliberate; very short bursts, gradual cadence drift and periodic irregular schedules may remain uncertain deviations. Gap candidates at the end of a bounded window can be unresolved. These limits are retained in evidence instead of retrospectively changing causal scores."]
    save("M11_SAMPLING_REGIMES.md",lines)
    (BASE/"reports/sampling_regime_details.md").write_text("\n".join(detail)+"\n",encoding="utf-8")

    lines=["# Threshold calibration report","","No final-test labels were used to select thresholds, detector parameters, window lengths or event grouping. Candidate design followed the requested forensic investigation of previously exposed M1 diagnostics; consequently this is not an externally blind validation.","",
      "Training learns a robust value scale and the median nonzero adjacent step. The new local denominator floor is `max(0.5 × training step, 0.1 × training robust sigma, epsilon × level)`. This prevents a quantized ordinary step from being divided by a machine-scale epsilon. It is not a threshold chosen to improve a test metric.","",
      "Point and interval scores are calibrated independently at the predeclared 99th percentile of chronological validation scores, using the higher order statistic, with a minimum threshold of3. These are different score definitions and units from M1's fixed six-MAD threshold. Validation labels are not inputs; validation may contain anomalies. A 1% empirical score-tail budget is not a guaranteed physical false-alarm probability.","",
      "Interval activation requires 3 consecutive exceedances and releases below half its threshold. Point detections remain immediate. Temporal event merging bridges at most 2 local cadences; baselines use 1.5. These defaults were declared before new final scoring and were not searched against final metrics. The combined candidate adds IF only with half-threshold temporal corroboration.","",
      "| Case | Learned scale floor | Training positive-step median | Point threshold | Interval threshold | Point validation exceedance | Interval validation exceedance |",
      "|---|---:|---:|---:|---:|---:|---:|"]
    for case,report in reports.items():
        frozen=read(RUN/case/"model_configuration.json");m=frozen["models"]["temporal"];c=report["calibration"]
        lines.append(f"| {case} | {m['scale_floor']:.8g} | {m['median_positive_training_step']:.8g} | {c['point']['threshold']:.6g} | {c['interval']['threshold']:.6g} | {c['point']['validation_exceedance_fraction']:.6g} | {c['interval']['validation_exceedance_fraction']:.6g} |")
    lines += ["", "The statistical baseline retains threshold 6. IF retains contamination 0.01, deterministic seed 42, 100 trees, at most 10,000 training samples and two CPU workers. Temporal history is capped at 4096 observations; truncation is explicitly flagged. Its time windows are 8/120/480 confirmed cadences, and its point reference retains the previous 31 observations across a gap while exposing their age.","",
      "PCA is calibrated on its validation reconstruction-error tail after training-only robust scaling and PCA fitting. Every case persists `model_configuration.json` **before** final scoring, plus `validation_scores.parquet`, `threshold_calibration.json`, model artifacts and a frozen-configuration SHA256. Test mutations cannot change the stored model parameters or calibration, as verified by tests.","",
      "[Model configuration manifest and case artifact hashes](../artifacts/milestone11/comparison_final/manifest.json). Exact chronological boundaries and threshold evidence appear in each case's report/configuration files. Both split designs are retained, including the primary point-window case with zero positive events in its final partition."]
    save("M11_CALIBRATION.md",lines)

    lines=["# Event-level evaluation and ground-truth semantics","",
      "Official Mission 1 preparation initializes observations to nominal then overlays annotations, and explicitly states that training is not guaranteed normal. This supports nominal complement as a benchmark convention, not independently confirmed physical normality. [Official preparation code](https://raw.githubusercontent.com/kplabs-pl/ESA-ADB/main/notebooks/data-prep/Mission 1_semisupervised_prep_from_raw.py)","",
      "VYOM preserves original IDs and point/interval timestamps. Evaluation-only envelopes give point truth half the causally confirmed cadence at the preceding observation. Interval matching remains inclusive. Maximum-cardinality one-to-one matching prevents repeat credit. Reported F1 is VYOM's declared protocol, not ESA's official corrected event precision, alarming precision or affiliation score. [Official ESA metrics](https://raw.githubusercontent.com/kplabs-pl/ESA-ADB/main/timeeval/metrics/ESA_ADB_metrics.py)","",
      "Three views remain separate: annotation-supported recall with unknown negatives; label-independent event/sample burden; and precision/F1/false alarms under an explicit assumed-normal convention. Repeated events overlapping truth are reported separately from events outside any annotation. Target=NO supplies burden only, never supervised negatives.","",
      "False alarms/day use adjacent observed elapsed time excluding gaps larger than 3 contemporaneously expected cadences. No time is extrapolated beyond test endpoints. Point/interval value scoring is separate from resolved adaptive timestamp-gap candidates; a timestamp gap does not establish communication failure. Communication Gap labels are evaluated at event level, since the missing interval has no sample rows.","",
      "| Case | Model | Truth events | Matched | Unmatched | Missed | Duplicate overlaps | Outside any label | Events/day |",
      "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for row in rows:
        e,b=row["event"],row["burden"]
        lines.append(f"| {row['case']} | {row['model']} | {e['ground_truth_events']} | {e['tp']} | {e['fp']} | {e['fn']} | {b['redundant_overlapping_events']} | {b['events_outside_any_label']} | {f(b['events_per_observation_day'])} |")
    lines += ["", "## Category and point/interval evidence","",
      "Each case's `report.json` contains `per_category` results for Anomaly/Rare Event, `per_geometry` point/interval views, original and effective truth timestamps, matched IDs and prediction intervals. Communication Gap results are separate in `communication_gaps`. `events.jsonl` includes duration, peak score, peak time and annotation IDs. Scores retain model-specific units and are not probabilities.","",
      "| Case | Adaptive gap predictions | Communication Gap truth | Matched | Missed |",
      "|---|---:|---:|---:|---:|"]
    for case,r in reports.items():
        e=r["communication_gaps"]["event"]["assumed_normal"]
        lines.append(f"| {case} | {e['predicted_events']} | {e['ground_truth_events']} | {e['tp']} | {e['fn']} |")
    lines += ["", "The positive-window interval-specific strategy still emits multiple fragments within one truth interval. Strict one-to-one precision penalizes these as unmatched predictions; the duplicate-overlap column distinguishes them from outside-annotation burden. No duplicate true positives are manufactured.","",
      "The old point miss was not a label tolerance error: its timestamp exactly exists. The repaired point strategy retains prior observations across the 16.7-hour gap and marks that reference stale. This can also alert on legitimate post-gap state changes; operator interpretation and broader validation remain necessary.","",
      "[Full comparison manifest](../artifacts/milestone11/comparison_final/manifest.json) · [Root-cause and primary-source investigation](M11_ROOT_CAUSES.md)"]
    save("M11_EVENT_EVALUATION.md",lines)
    print(f"Rendered four reports from {len(reports)} cases / {len(rows)} candidate comparisons")


if __name__=="__main__":
    main()
