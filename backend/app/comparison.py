"""Bounded Milestone 1.1 experiments, reusing the existing storage and models.

This runner intentionally refuses full-dataset analysis. It freezes training,
validation calibration and grouping configuration before final-test scoring.
"""
from dataclasses import asdict, dataclass
import argparse
import json
import logging
from pathlib import Path
import platform
import time

import joblib
import numpy as np
import pandas as pd

from app.artifacts import ResourceMonitor, atomic_json, configure_logging, file_sha256, fingerprint, run_lock, utc_now
from app.cadence import SamplingRegimeTracker, training_cadence
from app.calibration import split_manifest, QuantileCalibrator, DetectionPolicy
from app.detectors import StatisticalDetector, IsolationForestDetector, PCAReconstructionDetector, align_channels
from app.features import TemporalFeatureBuilder
from app.scientific import evaluate_detector
from app.storage import dataset_identity, iter_channel_batches
from app.telemetry import metadata, annotations, resolve_dataset
from app.temporal import TemporalDetector, TemporalEventGrouper


@dataclass(frozen=True)
class ComparisonConfig:
    max_rows: int = 20000
    batch_size: int = 5000
    max_train_rows: int = 10000
    seed: int = 42
    n_estimators: int = 100
    validation_tail_probability: float = .01
    minimum_temporal_threshold: float = 3.
    interval_persistence_samples: int = 3
    release_ratio: float = .5
    bridge_cadences: float = 2.

    def __post_init__(self):
        if not 100 <= self.max_rows <= 100000:
            raise ValueError("This pilot runner requires 100..100000 rows per window; full analysis is intentionally disabled")
        if self.batch_size < 1 or self.max_train_rows < 30:
            raise ValueError("Invalid batch or training sample budget")


def _measured(call):
    with ResourceMonitor() as monitor:
        result = call()
    return result, monitor.measurements


def _write_frame(path, frame):
    frame = frame.copy(deep=False)
    frame.index.name = "timestamp"
    temporary = Path(str(path)+".tmp")
    frame.to_parquet(temporary, engine="pyarrow", compression="zstd", row_group_size=5000)
    temporary.replace(path)


def _score_in_batches(call, frame, batch_size):
    return pd.concat([call(frame.iloc[start:start+batch_size]) for start in range(0,len(frame),batch_size)])


def _group(channel, index, flags, scores, cadence, name, bridge):
    grouper = TemporalEventGrouper(channel, bridge_cadences=bridge)
    return grouper.update(index, flags, scores, cadence, name,
             evidence={"score_semantics": "candidate-specific score; not a probability"}) + grouper.flush()


def run_window(raw, channel, ann, directory, config=None, train_fraction=.6,
               validation_fraction=.2, labelled_channel=True, pca_matrix=None, alignment=None):
    """Fit/calibrate only prefixes; annotations are accessed only after freeze."""
    config = config or ComparisonConfig()
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if len(raw) > config.max_rows:
        raise ValueError("Window exceeds the bounded pilot configuration")
    split = split_manifest(raw.index, train_fraction, validation_fraction)
    a,b = split["train_stop"],split["validation_stop"]
    initial = training_cadence(raw.index[:a])
    cadence_tracker = SamplingRegimeTracker(initial)
    timing_prefix, cadence_resources = _measured(lambda: cadence_tracker.transform(raw.index[:b]))
    cadence_tracker.drain_gaps()  # training/validation gaps never count as final-test predictions
    legacy_builder = TemporalFeatureBuilder(initial)
    legacy_prefix, feature_resources = _measured(lambda: _score_in_batches(legacy_builder.transform,raw.iloc[:b],config.batch_size))
    stat, stat_fit = _measured(lambda: StatisticalDetector(6.).fit(legacy_prefix.iloc[:a],train_end=split["train_end"]))
    iso, iso_fit = _measured(lambda: IsolationForestDetector(seed=config.seed, max_train_rows=config.max_train_rows,
             n_estimators=config.n_estimators,batch_size=config.batch_size).fit(legacy_prefix.iloc[:a], train_end=split["train_end"]))
    temporal, temporal_fit = _measured(lambda: TemporalDetector().fit(raw.iloc[:a],train_end=split["train_end"]))
    temporal_prefix, temporal_prefix_resources = _measured(lambda: _score_in_batches(
         lambda block: temporal.score(block,timing_prefix.loc[block.index,"cadence_seconds"].to_numpy()),raw.iloc[:b],config.batch_size))
    point_cal = QuantileCalibrator(config.validation_tail_probability,config.minimum_temporal_threshold).fit(
        temporal_prefix.point_score.iloc[a:b], validation_end=split["validation_end"])
    interval_cal = QuantileCalibrator(config.validation_tail_probability,config.minimum_temporal_threshold).fit(
        temporal_prefix.interval_score.iloc[a:b], validation_end=split["validation_end"])
    policy = DetectionPolicy(point_cal.threshold,interval_cal.threshold,config.interval_persistence_samples,config.release_ratio)
    policy.apply(temporal_prefix)  # causal detector state is warmed without any test labels
    calibration = {"point": point_cal.metadata(), "interval": interval_cal.metadata()}
    pca = None
    pca_fit = None
    if pca_matrix is not None:
        if not pca_matrix.index.equals(raw.index):
            raise ValueError("PCA and univariate comparators must use identical aligned timestamps")
        pca, pca_fit = _measured(lambda: PCAReconstructionDetector(seed=config.seed,max_train_rows=config.max_train_rows).fit(
            pca_matrix.iloc[:a],alignment=alignment,train_end=split["train_end"]))
        validation_prediction, pca_validation_resources = _measured(lambda: pca.score(pca_matrix.iloc[a:b]))
        validation_errors = validation_prediction.pca_error
        pca_cal = QuantileCalibrator(config.validation_tail_probability).fit(validation_errors,validation_end=split["validation_end"])
        calibration["pca"] = {**pca_cal.metadata(), "training_threshold":pca.threshold}
        pca.threshold = pca_cal.threshold
        joblib.dump(pca,directory/"pca.joblib")
    frozen = {"frozen_at": utc_now(), "split": split, "configuration": asdict(config),
        "initial_cadence_seconds": initial, "cadence": cadence_tracker.metadata(),
        "models": {"robust_statistical":stat.metadata(), "isolation_forest":iso.metadata(), "temporal":temporal.metadata()},
        "calibration":calibration,
        "grouping": {"baseline_bridge_cadences":1.5,"temporal_bridge_cadences":config.bridge_cadences,
                     "interval_persistence_samples":config.interval_persistence_samples,"release_ratio":config.release_ratio},
        "combination":"temporal point OR interval OR (IF AND half-threshold temporal corroboration)",
        "labels_used_for_training_or_calibration":False,
        "calibration_objective":"predeclared 1% validation score-tail budget, no label-based optimization",
        "pca":pca.metadata() if pca is not None else {"status":"not_applicable_to_univariate_window"},
        "random_forest":{"status":"skipped","reason":"No independently confirmed negative training labels supplied"}}
    atomic_json(directory/"model_configuration.json", frozen)
    freeze_sha = file_sha256(directory/"model_configuration.json")
    joblib.dump(iso,directory/"isolation_forest.joblib")
    joblib.dump(temporal,directory/"temporal.joblib")
    _write_frame(directory/"validation_scores.parquet",temporal_prefix.iloc[a:b])

    # Final observations and labels are first used after the configuration is persisted.
    test = raw.iloc[b:]
    timing_test, timing_test_resources = _measured(lambda: cadence_tracker.transform(test.index))
    gaps = cadence_tracker.drain_gaps()+cadence_tracker.finish()
    timing = pd.concat([timing_prefix,timing_test])
    legacy_test, feature_test_resources = _measured(lambda: _score_in_batches(legacy_builder.transform,test,config.batch_size))
    stat_test, stat_score_resources = _measured(lambda: stat.score(legacy_test))
    iso_test, iso_score_resources = _measured(lambda: iso.score(legacy_test))
    temporal_test, temporal_score_resources = _measured(lambda: _score_in_batches(
         lambda block: temporal.score(block,timing_test.loc[block.index,"cadence_seconds"].to_numpy()),test,config.batch_size))
    temporal_flags = policy.apply(temporal_test)
    ratio = np.maximum(temporal_test.point_score/point_cal.threshold, temporal_test.interval_score/interval_cal.threshold)
    corroborated_if = iso_test.iforest_flag & (ratio > config.release_ratio)
    model_predictions = {
        "robust_statistical": (stat_test.statistical_flag,stat_test.statistical_score,1.5),
        "isolation_forest": (iso_test.iforest_flag,iso_test.iforest_score,1.5),
        "temporal_point": (temporal_flags.point_flag,temporal_test.point_score,config.bridge_cadences),
        "temporal_interval": (temporal_flags.interval_flag,temporal_test.interval_score,config.bridge_cadences),
        "improved_temporal": (temporal_flags.temporal_flag,ratio,config.bridge_cadences),
        # IF abstains when its short-window history is unavailable. It must not
        # erase a valid post-gap temporal score through NaN propagation.
        "combined": (temporal_flags.temporal_flag | corroborated_if, np.fmax(ratio,iso_test.iforest_score/(-iso.model.offset_)),config.bridge_cadences)}
    measured = {"robust_statistical":[feature_resources,feature_test_resources,stat_fit,stat_score_resources],
                "isolation_forest":[feature_resources,feature_test_resources,iso_fit,iso_score_resources]}
    temporal_measured = [temporal_fit,temporal_prefix_resources,temporal_score_resources,cadence_resources,timing_test_resources]
    for name in ("temporal_point","temporal_interval","improved_temporal"):
        measured[name]=temporal_measured
    measured["combined"] = temporal_measured+measured["isolation_forest"]
    if pca is not None:
        prediction, pca_score_resources = _measured(lambda:pca.score(pca_matrix.iloc[b:]))
        model_predictions["pca_experimental"] = (prediction.pca_flag,prediction.pca_error,config.bridge_cadences)
        measured["pca_experimental"]=[pca_fit,pca_validation_resources,pca_score_resources]
    result = {"channel":channel,"split":split,"calibration":calibration,
        "frozen_configuration_sha256":freeze_sha,"models":{},"status":"completed",
        "initial_cadence_seconds":initial,"regimes":cadence_tracker.regimes(),
        "history_truncation_rows":int(temporal_test.truncated_history.sum()),
        "post_gap_test_rows":int(temporal_test.point_reference_stale.sum()),
        "interpretation":"Development-exposed diagnostic windows; final partitions excluded from fitting/calibration but not a new blind benchmark"}
    predictions = pd.DataFrame({"value":test},index=test.index)
    for name,(flags,scores,bridge) in model_predictions.items():
        flags = np.asarray(flags,bool)
        scores = np.asarray(scores,float)
        event_start = time.perf_counter()
        events = _group(channel,test.index,flags,scores,timing_test.cadence_seconds,name,bridge)
        event_seconds = time.perf_counter()-event_start
        evaluation = evaluate_detector(test.index,flags,scores,events,ann,timing,labelled_channel=labelled_channel)
        evaluation["resources"] = {"measured_processing_seconds":round(sum(m["wall_seconds"] for m in measured[name])+event_seconds,6),
            "peak_sampled_process_rss_mib":max(m["peak_sampled_rss_mib"] for m in measured[name]),
            "stages":measured[name],"event_grouping_seconds":event_seconds,
            "note":"Sum of measured dependent stages; shared feature stages reused, absolute process RSS includes resident arrays; evaluation/IO excluded"}
        result["models"][name]=evaluation
        predictions[name+"_flag"],predictions[name+"_score"]=flags,scores
    test_gaps=[]
    for gap in gaps:
        if pd.Timestamp(gap["start"]) < test.index[0] or pd.Timestamp(gap["end"]) > test.index[-1]:
            continue
        test_gaps.append({**gap,"channel":channel,"evidence":{"cause":"unknown","resolved_at":gap["resolved_at"],"resolution":gap["resolution"]}})
    result["communication_gaps"] = evaluate_detector(test.index,np.zeros(len(test),bool),np.zeros(len(test)),test_gaps,
                         ann,timing,labelled_channel=labelled_channel,gap_task=True)
    predictions=predictions.join(temporal_test.add_prefix("temporal_feature_"))
    _write_frame(directory/"predictions.parquet",predictions)
    _write_frame(directory/"cadence.parquet",timing)
    # Labels and annotation-linked event evidence are written only after final scoring.
    atomic_json(directory/"report.json",result)
    atomic_json(directory/"threshold_calibration.json",calibration)
    with (directory/"events.jsonl").open("w",encoding="utf-8") as stream:
        for name,report in result["models"].items():
            for event in report["events"]:
                stream.write(json.dumps({"model":name,**event},default=str)+"\n")
        for event in result["communication_gaps"]["events"]:
            stream.write(json.dumps({"model":"adaptive_gap",**event},default=str)+"\n")
    assert file_sha256(directory/"model_configuration.json")==freeze_sha
    return result


def _read_window(store,channel,config,start=None):
    batches=iter_channel_batches(store,channel,batch_size=config.batch_size,max_rows=config.max_rows,start=start)
    frame=pd.concat(list(batches))
    if frame.shape[1]!=1:
        raise ValueError("Pilot comparison requires an explicit single telemetry column")
    return frame.iloc[:,0]


def run_comparison(root,store,output,config=None):
    root,store,output=Path(root).resolve(),Path(store).resolve(),Path(output).resolve()
    config=config or ComparisonConfig()
    protected=[root,store,*[store.parent/name for name in ("pilot","pilot_annotation_interval","pilot_annotation_point")]]
    if any(output==p or p in output.parents or output in p.parents for p in protected):
        raise ValueError("Comparison output must not overlap source, store or preserved pilot artifacts")
    meta=metadata(root)
    identity=dataset_identity(root)
    ingestion=json.loads((store/"manifest.json").read_text())
    selected=["channel_1","channel_12","channel_41","channel_61","channel_74"]
    for channel in selected:
        entry=ingestion["channels"].get(channel,{})
        if entry.get("status")!="completed" or entry.get("source")!=identity["sources"].get(channel):
            raise ValueError(f"{channel}: current completed ingestion is required")
        if file_sha256(entry["path"])!=entry["file_sha256"]:
            raise ValueError(f"{channel}: Parquet integrity mismatch")
    code={p.name:file_sha256(p) for p in Path(__file__).parent.glob("*.py")}
    run_id=fingerprint({"configuration":asdict(config),"dataset":identity,"code":code})
    with run_lock(output):
        with ResourceMonitor() as total:
            manifest_path=output/"manifest.json"
            if manifest_path.exists():
                manifest=json.loads(manifest_path.read_text())
                if manifest["configuration_id"]!=run_id:
                    raise ValueError("Configuration or code changed; use a new comparison output directory")
            else:
                manifest={"created_at":utc_now(),"configuration_id":run_id,"configuration":asdict(config),"dataset":identity,
                    "code_sha256":code,"python":platform.python_version(),"cases":{},
                    "predeclared_splits":[{"name":"60_20_20","train":.6,"validation":.2},
                                          {"name":"50_20_30","train":.5,"validation":.2}],
                    "split_rationale":"Primary recommended60/20/20; secondary divides former70% development prefix and preserves original30% holdout. Report both; do not select by test metrics.",
                    "scope":"five representative prefixes and two known annotation windows only; no full76 benchmark",
                    "ground_truth":"Official nominal-by-default benchmark convention; physical normality is not independently verified"}
            manifest["status"]="running"
            atomic_json(manifest_path,manifest)
            windows=[(f"prefix_{c}",c,None) for c in selected]+[
                ("interval_channel_12","channel_12","2000-03-01T00:00:00Z"),
                ("point_channel_61","channel_61","2006-11-01T00:00:00Z")]
            try:
                for window,channel,start in windows:
                    raw=_read_window(store,channel,config,start)
                    for split in manifest["predeclared_splits"]:
                        case=f"{window}/{split['name']}"
                        old=manifest["cases"].get(case,{})
                        if old.get("status")=="completed" and all((output/case/p).is_file() and file_sha256(output/case/p)==h for p,h in old.get("artifact_sha256",{}).items()) and old.get("artifact_sha256"):
                            logging.info("comparison resume case=%s",case)
                            continue
                        logging.info("comparison start case=%s",case)
                        with ResourceMonitor() as monitor:
                            report=run_window(raw,channel,annotations(meta["labels"],meta["anomaly_types"],channel),output/case,
                                config,split["train"],split["validation"],
                                labelled_channel=str(meta["channels"].set_index("Channel").loc[channel,"Target"])=="YES")
                        manifest["cases"][case]={"status":"completed","channel":channel,"start":start,"split":report["split"],
                            "report":str(output/case/"report.json"),"resources":monitor.measurements,
                            "artifact_sha256":{p.name:file_sha256(p) for p in (output/case).iterdir() if p.is_file()}}
                        atomic_json(manifest_path,manifest)
                # Same anonymous unit, explicit common30s aggregation; exploratory
                # cross-subsystem pairing does not establish engineering correlation.
                pair={c:_read_window(store,c,config) for c in ("channel_41","channel_74")}
                common_start=max(s.index[0] for s in pair.values());common_end=min(s.index[-1] for s in pair.values())
                pair={c:s.loc[(s.index>=common_start)&(s.index<=common_end)] for c,s in pair.items()}
                units=meta["channels"].set_index("Channel")["Physical Unit"].to_dict()
                aligned,alignment=align_channels(pair,"30s",{c:units[c] for c in pair},max_rows=config.max_rows)
                alignment["interpretation"]="Same anonymous unit, different subsystems; exploratory relationship only; no physical correlation asserted"
                for split in manifest["predeclared_splits"]:
                    for channel in pair:
                        case=f"pca_aligned_{channel}/{split['name']}"
                        old=manifest["cases"].get(case,{})
                        if old.get("status")=="completed" and old.get("artifact_sha256") and all((output/case/p).is_file() and file_sha256(output/case/p)==h for p,h in old["artifact_sha256"].items()):
                            continue
                        logging.info("comparison start case=%s rows=%d",case,len(aligned))
                        with ResourceMonitor() as monitor:
                            report=run_window(aligned[channel],channel,annotations(meta["labels"],meta["anomaly_types"],channel),output/case,
                                 config,split["train"],split["validation"],True,pca_matrix=aligned,alignment=alignment)
                        manifest["cases"][case]={"status":"completed","channel":channel,"split":report["split"],"alignment":alignment,
                            "report":str(output/case/"report.json"),"resources":monitor.measurements,
                            "artifact_sha256":{p.name:file_sha256(p) for p in (output/case).iterdir() if p.is_file()}}
                        atomic_json(manifest_path,manifest)
            except BaseException as exc:
                manifest.update(status="interrupted" if isinstance(exc,KeyboardInterrupt) else "failed",error=f"{type(exc).__name__}: {exc}")
                atomic_json(manifest_path,manifest)
                raise
            manifest.update(status="completed",completed_at=utc_now())
        manifest.setdefault("executions",[]).append(total.measurements)
        manifest.pop("error",None)
        atomic_json(manifest_path,manifest)
        return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset",default="../data/esa_adb/mission1/ESA-Mission1")
    parser.add_argument("--store",type=Path,default=Path("../artifacts/telemetry"))
    parser.add_argument("--output",type=Path,default=Path("../artifacts/milestone11/comparison_final"))
    args=parser.parse_args()
    configure_logging()
    result=run_comparison(resolve_dataset(args.dataset),args.store,args.output)
    print(json.dumps({"status":result["status"],"cases":len(result["cases"]),"resources":result["executions"][-1]}))


if __name__=="__main__":
    main()
