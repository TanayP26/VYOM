"""Resumable, bounded-memory chronological telemetry experiments.

The standard runner evaluates univariate statistical/Isolation Forest ensembles.
PCA and supervised baselines are explicit experiments in app.detectors; their
alignment and negative-label assumptions must be supplied by the caller.
"""
from dataclasses import asdict, dataclass, field
import importlib.metadata
import json
import logging
from pathlib import Path
import platform

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from app.artifacts import atomic_json, file_sha256, fingerprint, ResourceMonitor, run_lock, utc_now
from app.detectors import IsolationForestDetector, StatisticalDetector
from app.events import AnnotationMatcher, EventGrouper, gap_events
from app.evaluation import (EventMetricAccumulator, binary_counts, label_samples,
                            metrics_from_counts, observation_seconds)
from app.features import FeatureConfig, TemporalFeatureBuilder
from app.storage import dataset_identity, iter_channel_batches
from app.telemetry import annotations, metadata

LOG = logging.getLogger(__name__)
DETECTORS = ("statistical", "isolation_forest", "combined")
VALUE_CATEGORIES = ("Anomaly", "Rare Event")


@dataclass(frozen=True)
class ExperimentConfig:
    train_fraction: float = .7
    batch_size: int = 25000
    max_rows: int | None = None
    max_train_rows: int = 20000
    seed: int = 42
    contamination: float = .01
    statistical_threshold: float = 6.0
    statistical_quantile: float | None = None
    gap_factor: float = 3.0
    point_tolerance_cadences: float = .5
    unlabelled_policy: str = "exclude"
    n_estimators: int = 100
    start: str | None = None
    end: str | None = None
    features: FeatureConfig = field(default_factory=FeatureConfig)

    def __post_init__(self):
        if not 0 < self.train_fraction < 1:
            raise ValueError("train_fraction must be between 0 and 1")
        if self.batch_size < 1 or self.max_train_rows < 30:
            raise ValueError("batch_size must be positive and max_train_rows >= 30")
        if self.max_rows is not None and self.max_rows < 50:
            raise ValueError("max_rows must allow at least 50 chronological observations")
        if self.unlabelled_policy not in {"exclude", "assume_normal"}:
            raise ValueError("unlabelled_policy must be exclude or assume_normal")
        if self.gap_factor <= 1 or self.point_tolerance_cadences < 0:
            raise ValueError("gap_factor must exceed 1 and point tolerance cannot be negative")
        if not 0 < self.contamination <= .5 or self.n_estimators < 1:
            raise ValueError("Invalid Isolation Forest configuration")


def _source_code_identity():
    return {p.name: file_sha256(p) for p in sorted(Path(__file__).parent.glob("*.py"))}


def _raw_batches(store, channel, config):
    return iter_channel_batches(store, channel, batch_size=config.batch_size,
                                start=config.start, end=config.end, max_rows=config.max_rows)


def _feature_batches(path, batch_size, limit=None, skip=0):
    seen = 0
    yielded = 0
    for batch in pq.ParquetFile(path).iter_batches(batch_size=batch_size):
        frame = batch.to_pandas()
        frame.index = pd.DatetimeIndex(pd.to_datetime(frame.pop("timestamp"), utc=True))
        stop = seen + len(frame)
        if stop <= skip:
            seen = stop
            continue
        frame = frame.iloc[max(0, skip - seen):]
        seen = stop
        if limit is not None:
            frame = frame.iloc[:max(0, limit - yielded)]
        if len(frame):
            yield frame
            yielded += len(frame)
        if limit is not None and yielded >= limit:
            break


def _training_sample(path, train_rows, config):
    """Seeded uniform priority reservoir, bounded to max_train_rows + one batch."""
    rng = np.random.default_rng(config.seed)
    sample = None
    priorities = np.empty(0)
    for batch in _feature_batches(path, config.batch_size, limit=train_rows):
        priorities = np.r_[priorities, rng.random(len(batch))]
        sample = batch if sample is None else pd.concat([sample, batch])
        if len(sample) > config.max_train_rows:
            keep = np.argpartition(priorities, config.max_train_rows - 1)[:config.max_train_rows]
            sample = sample.iloc[keep]
            priorities = priorities[keep]
    if sample is None:
        raise ValueError("Empty training selection")
    return sample.sort_index()


def _make_features(store, channel, directory, config, available_rows):
    if config.start is not None or config.end is not None:
        rows = sum(len(b) for b in _raw_batches(store, channel, config))
    else:
        rows = min(available_rows, config.max_rows or available_rows)
    if rows < 50:
        raise ValueError(f"{channel}: selection contains {rows} rows; at least 50 are required")
    train_rows = int(rows * config.train_fraction)
    # Learn cadence from the training prefix only, including no held-out timestamps.
    timing = []
    count = 0
    for batch in _raw_batches(store, channel, config):
        n = min(len(batch), train_rows - count, 10000 - count)
        timing.extend(batch.index[:n])
        count += n
        if count >= min(train_rows, 10000):
            break
    times = pd.DatetimeIndex(timing).as_unit("ns").asi8
    cadence = float(np.median(np.diff(times)) / 1e9)
    if not np.isfinite(cadence) or cadence <= 0:
        raise ValueError(f"{channel}: unable to estimate a positive training cadence")
    builders, writers, paths = {}, {}, {}
    seen = 0
    selection = {"rows": rows, "train_rows": train_rows, "test_rows": rows - train_rows,
                 "cadence_seconds": cadence, "cadence_fit_rows": len(timing),
                 "cadence_source": "first up to 10000 training timestamps only"}
    try:
        for frame in _raw_batches(store, channel, config):
            if not builders:
                selection["start"] = frame.index[0].isoformat()
                for i, column in enumerate(frame.columns):
                    builders[str(column)] = TemporalFeatureBuilder(cadence, config.features)
                    paths[str(column)] = directory / f"features_{i}.parquet"
            if seen < train_rows <= seen + len(frame):
                selection["train_end"] = frame.index[train_rows - seen - 1].isoformat()
            if seen <= train_rows < seen + len(frame):
                selection["test_start"] = frame.index[train_rows - seen].isoformat()
            for column in frame.columns:
                name = str(column)
                features = builders[name].transform(frame[column])
                features.insert(0, "timestamp", features.index)
                table = pa.Table.from_pandas(features, preserve_index=False)
                if name not in writers:
                    writers[name] = pq.ParquetWriter(str(paths[name]) + ".tmp", table.schema,
                                                   compression="zstd")
                writers[name].write_table(table, row_group_size=min(config.batch_size, 250000))
            seen += len(frame)
            selection["end"] = frame.index[-1].isoformat()
            LOG.info("features channel=%s rows=%d/%d", channel, seen, rows)
    finally:
        for writer in writers.values():
            writer.close()
    if seen != rows:
        raise RuntimeError(f"{channel}: expected {rows} selected rows but read {seen}")
    for path in paths.values():
        Path(str(path) + ".tmp").replace(path)
    atomic_json(directory / "features.json", {"selection": selection,
                "configuration": next(iter(builders.values())).metadata(),
                "files": {key: str(path.resolve()) for key, path in paths.items()}})
    return paths, selection


def _add_counts(total, update):
    for key in ("tp", "fp", "tn", "fn", "excluded_unknown"):
        total[key] = total.get(key, 0) + int(update.get(key, 0))


def _channel_analysis(root, store, channel, directory, config, source_entry, meta):
    directory.mkdir(parents=True, exist_ok=True)
    paths, selection = _make_features(store, channel, directory, config, source_entry["rows"])
    models = {}
    model_meta = {}
    for i, (column, path) in enumerate(paths.items()):
        sample = _training_sample(path, selection["train_rows"], config)
        stat = StatisticalDetector(threshold=config.statistical_threshold,
                                   quantile=config.statistical_quantile,
                                   max_train_rows=config.max_train_rows, seed=config.seed).fit(
                                       sample, train_end=selection["train_end"])
        iso = IsolationForestDetector(contamination=config.contamination, seed=config.seed,
                max_train_rows=config.max_train_rows, batch_size=config.batch_size,
                n_estimators=config.n_estimators).fit(sample, train_end=selection["train_end"])
        model_path = directory / f"isolation_forest_{i}.joblib"
        iso.save(model_path)
        models[column] = (stat, iso)
        model_meta[column] = {"isolation_forest": iso.metadata(),
                              "statistical": stat.metadata(),
                              "training_sample_rows": len(sample),
                              "sampling": "seeded uniform priority reservoir over training prefix",
                              "artifact": str(model_path.resolve())}
        del sample
    ann = annotations(meta["labels"], meta["anomaly_types"], channel)
    target = str(meta["channels"].set_index("Channel").loc[channel, "Target"]).upper()
    labelled = target == "YES" and not ann.empty
    tolerance = pd.Timedelta(seconds=selection["cadence_seconds"] * config.point_tolerance_cadences)
    begin, end = pd.Timestamp(selection["test_start"]), pd.Timestamp(selection["end"])
    # Do not truncate original truth intervals or IDs. Include only those intersecting
    # the observed test horizon (points use the declared cadence tolerance).
    point = ann.StartTime == ann.EndTime
    eligible_truth = ((ann.EndTime >= begin) & (ann.StartTime <= end)) | (
        point & (ann.StartTime + tolerance >= begin) & (ann.StartTime - tolerance <= end))
    test_ann = ann.loc[eligible_truth].copy()
    value_ann = test_ann[test_ann.Category.isin(VALUE_CATEGORIES)]
    gap_ann = test_ann[test_ann.Category == "Communication Gap"]
    annotation_matcher = AnnotationMatcher(test_ann, point_tolerance=tolerance)
    accumulators = {name: EventMetricAccumulator(value_ann, point_tolerance=tolerance,
                    unlabelled_policy=config.unlabelled_policy if labelled else "exclude",
                    labelled_channel=labelled)
                    for name in DETECTORS}
    category_events = {category: EventMetricAccumulator(value_ann[value_ann.Category == category],
                       point_tolerance=tolerance,
                       unlabelled_policy=config.unlabelled_policy if labelled else "exclude",
                       labelled_channel=labelled)
                       for category in VALUE_CATEGORIES}
    gap_accumulator = EventMetricAccumulator(gap_ann, point_tolerance=tolerance,
                          unlabelled_policy=config.unlabelled_policy if labelled else "exclude",
                          labelled_channel=labelled)
    groupers = {name: EventGrouper(channel, selection["cadence_seconds"]) for name in DETECTORS}
    counts = {name: dict(tp=0, fp=0, tn=0, fn=0) for name in DETECTORS}
    category_counts = {name: dict(tp=0, fp=0, tn=0, fn=0) for name in VALUE_CATEGORIES}
    eligible_rows = 0
    gap_excluded_rows = 0
    exposure = 0.0
    previous = None  # Never use a train->test gap as a held-out prediction.
    event_counts = {name: 0 for name in (*DETECTORS, "timestamp_gap")}
    event_path = directory / "events.jsonl"
    prediction_path = directory / "predictions.parquet"
    writer = None
    iterations = [_feature_batches(path, config.batch_size, skip=selection["train_rows"])
                  for path in paths.values()]
    def emit(event, stream):
        kind = event["detector"]
        event = annotation_matcher.correlate(event)
        stream.write(json.dumps(event, default=str, allow_nan=False) + "\n")
        event_counts[kind] += 1
        if kind == "timestamp_gap":
            gap_accumulator.update(event)
        else:
            accumulators[kind].update(event)
            if kind == "combined":
                for metric in category_events.values():
                    metric.update(event)

    with Path(str(event_path) + ".tmp").open("w", encoding="utf-8") as stream:
        try:
            for frames in zip(*iterations, strict=True):
                index = frames[0].index
                predictions = pd.DataFrame(index=index)
                predictions["timestamp"] = index
                for name in DETECTORS:
                    predictions[f"{name}_flag"] = False
                    predictions[f"{name}_score"] = 0.0
                for (column, (stat, iso)), frame in zip(models.items(), frames, strict=True):
                    if not frame.index.equals(index):
                        raise RuntimeError("Feature column timelines diverged")
                    statistical = stat.score(frame)
                    isolation = iso.score(frame)
                    for name, result, prefix in (("statistical", statistical, "statistical"),
                                                   ("isolation_forest", isolation, "iforest")):
                        predictions[f"{name}_flag"] |= result[f"{prefix}_flag"].to_numpy()
                        predictions[f"{name}_score"] = np.maximum(
                            predictions[f"{name}_score"], result[f"{prefix}_score"].fillna(0).to_numpy())
                    # Normalize each detector by its own fitted threshold before
                    # combining. An IF-only candidate retains meaningful evidence.
                    stat_ratio = statistical.statistical_score.fillna(0).to_numpy() / max(stat.threshold, config.features.epsilon)
                    iso_ratio = isolation.iforest_score.fillna(0).to_numpy() / max(float(-iso.model.offset_), config.features.epsilon)
                    predictions["combined_score"] = np.maximum(predictions.combined_score,
                                                               np.maximum(stat_ratio, iso_ratio))
                predictions["combined_flag"] = predictions.statistical_flag | predictions.isolation_forest_flag
                labels = label_samples(index, value_ann, point_tolerance=tolerance,
                           unlabelled_policy=config.unlabelled_policy, labelled_channel=labelled)
                gap_labels = label_samples(index, gap_ann, point_tolerance=tolerance,
                           unlabelled_policy="exclude", labelled_channel=labelled)
                # Communication-gap-only evidence supplies no normal labels for
                # the value-detector task, even under assume_normal. Overlapping
                # Anomaly/Rare Event evidence remains a valid positive label.
                gap_only = (gap_labels.target.to_numpy() == 1) & ~labels.annotated.to_numpy()
                gap_excluded_rows += int(gap_only.sum())
                labels.loc[gap_only, "target"] = np.nan
                labels.loc[gap_only, "eligible"] = False
                mask = labels.eligible.to_numpy()
                eligible_rows += int(mask.sum())
                predictions["target"] = labels.target.to_numpy()
                predictions["evaluation_eligible"] = mask
                for name in DETECTORS:
                    _add_counts(counts[name], binary_counts(labels.target.to_numpy(),
                                predictions[f"{name}_flag"].to_numpy()))
                    for event in groupers[name].update(index, predictions[f"{name}_flag"],
                                predictions[f"{name}_score"], detector=name,
                                evidence={"columns": list(paths),
                                    "score_units": {"statistical": "MAD multiples", "isolation_forest": "negative IF score_samples",
                                                    "combined": "maximum score divided by its detector threshold"}[name],
                                    "prediction_artifact": str(prediction_path.resolve()),
                                    "combination": "OR of statistical and Isolation Forest flags" if name == "combined" else name}):
                        emit(event, stream)
                for category in VALUE_CATEGORIES:
                    labels_category = label_samples(index, value_ann, point_tolerance=tolerance,
                        unlabelled_policy=config.unlabelled_policy, category=category, labelled_channel=labelled)
                    labels_category.loc[gap_only, "target"] = np.nan
                    labels_category.loc[gap_only, "eligible"] = False
                    _add_counts(category_counts[category], binary_counts(labels_category.target.to_numpy(),
                        predictions.combined_flag.to_numpy()))
                for event in gap_events(index, selection["cadence_seconds"],
                            threshold_factor=config.gap_factor, previous_timestamp=previous, channel=channel):
                    event["detector"] = "timestamp_gap"
                    emit(event, stream)
                exposure += observation_seconds(index, selection["cadence_seconds"],
                            previous_timestamp=previous, gap_factor=config.gap_factor)
                previous = index[-1]
                table = pa.Table.from_pandas(predictions, preserve_index=False)
                if writer is None:
                    writer = pq.ParquetWriter(str(prediction_path) + ".tmp", table.schema, compression="zstd")
                writer.write_table(table, row_group_size=config.batch_size)
            for grouper in groupers.values():
                for event in grouper.flush():
                    emit(event, stream)
        finally:
            if writer is not None:
                writer.close()
    Path(str(event_path) + ".tmp").replace(event_path)
    Path(str(prediction_path) + ".tmp").replace(prediction_path)
    sample_metrics = {name: metrics_from_counts(value) for name, value in counts.items()}
    result = {"channel": channel, "status": "completed", "target": target,
        "label_status": "labelled" if labelled else "unlabelled", "selection": selection,
        "models": model_meta, "point_tolerance_seconds": tolerance.total_seconds(),
        "unlabelled_policy": config.unlabelled_policy,
        "eligible_test_rows": eligible_rows, "unknown_test_rows": selection["test_rows"] - eligible_rows,
        "excluded_gap_only_test_rows": gap_excluded_rows,
        "category_sample_task": "One category versus other annotated value categories; gap-only samples excluded",
        "observation_seconds": exposure, "event_counts": event_counts,
        "metrics": {"sample": sample_metrics,
                    "event": {name: metric.result(observation_seconds=exposure) for name, metric in accumulators.items()},
                    "per_category": {name: {"sample": metrics_from_counts(category_counts[name]),
                                     "event": category_events[name].result(observation_seconds=exposure)} for name in VALUE_CATEGORIES},
                    "communication_gap": {"event": gap_accumulator.result(observation_seconds=exposure),
                        "sample": None, "note": "Timestamp gaps have no observed samples inside their missing interval."}},
        "artifacts": {"events": str(event_path.resolve()), "predictions": str(prediction_path.resolve()),
                      "features": str((directory / "features.json").resolve())},
        "limitations": ["Metrics with assume_normal use unannotated periods as assumed normal only on labelled channels.",
             "Exclude-policy sample precision is conditional on annotated evidence; event precision, F1 and false-alarm rate are unavailable without assumed negatives.",
             "Candidate timestamp gaps do not prove communication failures.",
             "PCA requires explicit resampling/unit policy; supervised RF requires an explicit negative-label policy."]}
    result["metrics"]["per_category"]["Communication Gap"] = result["metrics"]["communication_gap"]
    return result


def _artifact_hashes(report, report_path):
    """Hash the complete channel artifact graph, not just its top-level JSON."""
    directory = report_path.parent.resolve()
    paths = {report_path.resolve(), *(Path(p).resolve() for p in report["artifacts"].values())}
    features = json.loads(Path(report["artifacts"]["features"]).read_text(encoding="utf-8"))
    paths.update(Path(p).resolve() for p in features["files"].values())
    paths.update(Path(model["artifact"]).resolve() for model in report["models"].values())
    if any(directory not in path.parents for path in paths):
        raise ValueError("Experiment artifact points outside its channel directory")
    return {str(path.relative_to(directory)): file_sha256(path) for path in sorted(paths)}


def _artifacts_valid(directory, hashes):
    if not hashes:
        return False
    directory = directory.resolve()
    try:
        for name, expected in hashes.items():
            path = (directory / name).resolve()
            if directory not in path.parents or file_sha256(path) != expected:
                return False
        return True
    except (OSError, TypeError, ValueError):
        return False


def _validate_ingested_sources(store, ingestion, identity, selected):
    if ingestion.get("dataset", {}).get("fingerprint") != identity["fingerprint"] or ingestion.get("dataset", {}).get("root") != identity["root"]:
        raise ValueError("Source dataset changed since ingestion; rerun ingestion before analysis")
    for channel in selected:
        entry = ingestion["channels"].get(channel, {})
        if entry.get("status") != "completed":
            raise ValueError(f"{channel} has no completed Parquet ingestion in {store}")
        if entry.get("source") != identity["sources"].get(channel):
            raise ValueError(f"{channel}: source fingerprint is stale; rerun ingestion")
        path = Path(entry["path"]).resolve()
        if path.parent != store:
            raise ValueError(f"{channel}: ingested artifact points outside the Parquet store")
        try:
            valid = (path.stat().st_size == entry["file_size_bytes"] and
                     file_sha256(path) == entry.get("file_sha256") and
                     pq.ParquetFile(path).metadata.num_rows == entry["rows"])
        except (OSError, pa.ArrowException):
            valid = False
        if not valid:
            raise ValueError(f"{channel}: ingested Parquet integrity check failed; rerun ingestion")


def run_experiment(root, store, output, channels=None, config=None, progress=None):
    """Resume completed channels; interrupted channels restart atomically from scratch."""
    root, store, output = Path(root).resolve(), Path(store).resolve(), Path(output).resolve()
    if (output == root or root in output.parents or output == store
            or store in output.parents or output in store.parents):
        raise ValueError("Experiment output must be outside the original dataset and separate from the store")
    config = config or ExperimentConfig()
    with run_lock(output):
        with ResourceMonitor() as monitor:
            ingestion = json.loads((store / "manifest.json").read_text(encoding="utf-8"))
            meta = metadata(root)
            selected = meta["channels"].Channel.astype(str).tolist() if channels is None else list(channels)
            if len(set(selected)) != len(selected) or not selected:
                raise ValueError("Select unique, nonempty channels")
            if set(selected) - set(meta["channels"].Channel.astype(str)):
                raise ValueError("Selected channel is not present in dataset metadata")
            identity = dataset_identity(root)
            _validate_ingested_sources(store, ingestion, identity, selected)
            source_entries = {name: ingestion["channels"][name] for name in selected}
            config_id = fingerprint({"config": asdict(config), "dataset": identity,
                     "channels": selected, "ingestion": source_entries, "code": _source_code_identity()})
            path = output / "manifest.json"
            if path.exists():
                manifest = json.loads(path.read_text(encoding="utf-8"))
                if manifest["configuration_id"] != config_id:
                    raise ValueError("Run configuration, dataset or code changed; choose a new --output directory")
            else:
                manifest = {"version": 1, "configuration_id": config_id, "dataset": identity,
                    "channel_coverage": selected, "configuration": asdict(config),
                    "created_at": utc_now(), "channels": {}, "artifacts": str(output),
                    "code_sha256": _source_code_identity(),
                    "environment": {"python": platform.python_version(), "packages": {
                        name: importlib.metadata.version(name) for name in ("numpy", "pandas", "pyarrow", "scikit-learn", "psutil")}},
                    "experimental_detectors": {"PCA": "available; skipped without explicit multivariate alignment and unit policy",
                        "RandomForest": "available; skipped without explicit negative labels or assume-normal training configuration"}}
            manifest.update(status="running", last_started_at=utc_now())
            atomic_json(path, manifest)
            try:
                for channel in selected:
                    report_path = output / channel / "report.json"
                    prior = manifest["channels"].get(channel, {})
                    if prior.get("status") == "completed" and _artifacts_valid(report_path.parent, prior.get("artifacts_sha256")):
                        report = json.loads(report_path.read_text(encoding="utf-8"))
                        LOG.info("resume channel=%s status=skipped_completed", channel)
                        if progress:
                            progress(channel, report)
                        continue
                    manifest["channels"][channel] = {"status": "running", "started_at": utc_now()}
                    atomic_json(path, manifest)
                    LOG.info("analysis channel=%s status=started", channel)
                    with ResourceMonitor() as channel_monitor:
                        report = _channel_analysis(root, store, channel, output / channel,
                                    config, source_entries[channel], meta)
                    report["resources"] = channel_monitor.measurements
                    atomic_json(report_path, report)
                    manifest["channels"][channel] = {"status": "completed", "completed_at": utc_now(),
                            "report": str(report_path), "selection": report["selection"],
                            "metrics": report["metrics"], "resources": report["resources"],
                            "artifacts_sha256": _artifact_hashes(report, report_path)}
                    atomic_json(path, manifest)
                    LOG.info("analysis channel=%s status=completed resources=%s", channel, channel_monitor.measurements)
                    if progress:
                        progress(channel, report)
                # Fail rather than certify artifacts against inputs changed by a
                # concurrent ingestion or source edit while this run was active.
                final_identity = dataset_identity(root)
                _validate_ingested_sources(store, ingestion, final_identity, selected)
                manifest.update(status="completed", completed_at=utc_now())
            except BaseException as exc:
                manifest.update(status="interrupted" if isinstance(exc, KeyboardInterrupt) else "failed",
                                error=f"{type(exc).__name__}: {exc}", failed_at=utc_now())
                if "channel" in locals() and manifest["channels"].get(channel, {}).get("status") == "running":
                    manifest["channels"][channel]["status"] = manifest["status"]
                atomic_json(path, manifest)
                raise
        manifest.setdefault("executions", []).append(monitor.measurements)
        manifest.pop("error", None)
        atomic_json(path, manifest)
    return manifest
