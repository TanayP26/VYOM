"""Separate M1.3 streaming runner; full execution requires a reviewed plan."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from app.artifacts import ResourceMonitor, file_sha256, fingerprint, run_lock, utc_now
from app.cadence import SamplingRegimeTracker, training_cadence
from app.calibration import DetectionPolicy
from app.operator_policy import operator_policy_metadata, temporal_first_operator_flags
from app.detectors import BoundedTrainingSampler, IsolationForestDetector, StatisticalDetector, _valid
from app.features import FeatureConfig, TemporalFeatureBuilder
from app.storage import atomic_json
from app.telemetry import annotations, resolve_dataset
from app.temporal import TemporalConfig
from app.streaming_checkpoint import FragmentJournal
from app.streaming_state import StreamingTemporalEventGrouper
from app.streaming_statistics import fit_temporal_stream, calibrate_stream

MODELS = ("robust_statistical", "isolation_forest", "temporal_point", "temporal_interval", "improved_temporal", "combined")
# M1/M1.1 scale=4 was retained as a diagnostic only. None of the M1.3
# robust-statistical / Isolation-Forest / combined comparator inputs consume
# median_scale_4, mad_scale_4 or robust_score_scale_4.
LEGACY_COMPARATOR_FEATURE_CONFIG = FeatureConfig(scales=(1,))
HISTORY_COMPATIBILITY_CEILING_ROWS = 50000
HISTORY_COMPATIBILITY = {
    "mode": "timestamp_only_exact_capacity_preflight",
    "default_guard_rows": 10000,
    "ceiling_rows": HISTORY_COMPATIBILITY_CEILING_ROWS,
    "feature_math_changed": False,
    "resampling": False,
    "adaptive_cadence_fed_to_legacy_features": False,
    "labels_used": False,
    "values_used": False,
    "interpretation": "Engineering compatibility extension for exact frozen fixed-time windows; never silent truncation",
}
PROTOCOL = {
    "version": 1, "fitting": "frozen_procedure_new_channel_specific_fitted_identity",
    "train_fraction": .6, "validation_fraction": .2, "seed": 42,
    "max_train_rows": 10000, "n_estimators": 100, "if_contamination": .01,
    "statistical_threshold": 6., "tail_probability": .01, "minimum_temporal_threshold": 3.,
    "persistence": 3, "release_ratio": .5, "baseline_bridge": 1.5, "temporal_bridge": 2.,
    "features": asdict(FeatureConfig()), "temporal": asdict(TemporalConfig()),
    "operator_policy": operator_policy_metadata(),
    "labels_used_for_fit": False, "Target_NO": "unknown; never supervised negatives",
    "A_B": "separate retrospective namespaces; neither is external blind validation",
    "history_compatibility": HISTORY_COMPATIBILITY,
}


def code_identity():
    return fingerprint({p.name: file_sha256(p) for p in Path(__file__).parent.glob("*.py")})


class ParquetChannel:
    """Ordinal seeking skips row groups, and decodes at most one bounded batch."""
    def __init__(self, path, base_row=0, rows=None, batch_size=5000, expected_sha256=None):
        self.path = Path(path).resolve()
        self.sha256 = file_sha256(self.path)
        if expected_sha256 and self.sha256 != expected_sha256:
            raise ValueError("Parquet source hash changed")
        with pq.ParquetFile(self.path) as parquet:
            total = parquet.metadata.num_rows
            if len(parquet.schema_arrow.names) != 2 or "timestamp" not in parquet.schema_arrow.names:
                raise ValueError("Streaming benchmark requires one explicit telemetry value column")
        self.base_row = base_row
        self.rows = total-base_row if rows is None else rows
        if batch_size < 1 or base_row < 0 or self.rows < 1 or base_row+self.rows > total:
            raise ValueError("Invalid bounded channel range")
        self.batch_size = batch_size
        self.read_seconds = 0.
        self.rows_read = 0
        self.timestamp_read_seconds = 0.
        self.timestamp_rows_read = 0

    def batches(self, start=0, stop=None):
        stop = self.rows if stop is None else stop
        if not 0 <= start <= stop <= self.rows:
            raise ValueError("Read range outside planned channel")
        lower, upper = self.base_row+start, self.base_row+stop
        with pq.ParquetFile(self.path) as parquet:
            offset = 0
            for group in range(parquet.num_row_groups):
                length = parquet.metadata.row_group(group).num_rows
                if offset+length <= lower:
                    offset += length
                    continue
                if offset >= upper:
                    break
                iterator = iter(parquet.iter_batches(row_groups=[group], batch_size=self.batch_size))
                while True:
                    begin = time.perf_counter()
                    try:
                        batch = next(iterator)
                    except StopIteration:
                        break
                    frame = batch.to_pandas()
                    if "timestamp" in frame:
                        frame = frame.set_index("timestamp")
                    elif frame.index.name != "timestamp":
                        raise ValueError("Parquet batch does not preserve timestamp identity")
                    frame.index = pd.DatetimeIndex(frame.index).tz_convert("UTC").as_unit("ns")
                    left, right = max(0, lower-offset), min(len(frame), upper-offset)
                    self.rows_read += len(frame)
                    offset += len(frame)
                    self.read_seconds += time.perf_counter()-begin
                    if left < right:
                        yield frame.iloc[left:right, 0]
                    if offset >= upper:
                        return

    def timestamp_batches(self, start=0, stop=None):
        """Read only timestamps for deterministic resource/capacity planning."""
        stop = self.rows if stop is None else stop
        if not 0 <= start <= stop <= self.rows:
            raise ValueError("Read range outside planned channel")
        lower, upper = self.base_row + start, self.base_row + stop
        with pq.ParquetFile(self.path) as parquet:
            offset = 0
            for group in range(parquet.num_row_groups):
                length = parquet.metadata.row_group(group).num_rows
                if offset + length <= lower:
                    offset += length; continue
                if offset >= upper: break
                iterator = iter(parquet.iter_batches(row_groups=[group], columns=["timestamp"], batch_size=self.batch_size))
                while True:
                    begin = time.perf_counter()
                    try: batch = next(iterator)
                    except StopIteration: break
                    index = pd.DatetimeIndex(batch.column(0).to_pandas())
                    index = index.tz_localize("UTC") if index.tz is None else index.tz_convert("UTC")
                    index = index.as_unit("ns")
                    left, right = max(0, lower-offset), min(len(index), upper-offset)
                    self.timestamp_rows_read += len(index)
                    offset += len(index)
                    self.timestamp_read_seconds += time.perf_counter()-begin
                    if left < right: yield index[left:right]
                    if offset >= upper: return

    def timestamp(self, ordinal):
        return next(self.batches(ordinal, ordinal+1)).index[0]

    def split(self, train_fraction=.6, validation_fraction=.2):
        a, b = int(self.rows*train_fraction), int(self.rows*(train_fraction+validation_fraction))
        if min(a, b-a, self.rows-b) < 2:
            raise ValueError("Each partition needs at least two rows")
        boundaries = [self.timestamp(i).isoformat() for i in (0, a-1, a, b-1, b, self.rows-1)]
        return dict(zip(("train_start", "train_end", "validation_start", "validation_end", "test_start", "test_end"), boundaries),
                    train_fraction=train_fraction, validation_fraction=validation_fraction,
                    test_fraction=1-train_fraction-validation_fraction, train_stop=a, validation_stop=b,
                    train_rows=a, validation_rows=b-a, test_rows=self.rows-b)


def locate_timestamp(path, timestamp, batch_size=5000):
    target = pd.Timestamp(timestamp)
    with pq.ParquetFile(path) as parquet:
        offset = 0
        column = parquet.schema_arrow.get_field_index("timestamp")
        for group in range(parquet.num_row_groups):
            metadata = parquet.metadata.row_group(group)
            stats = metadata.column(column).statistics
            if stats and stats.has_min_max and pd.Timestamp(stats.max) < target:
                offset += metadata.num_rows
                continue
            for batch in parquet.iter_batches(row_groups=[group], columns=["timestamp"], batch_size=batch_size):
                index = pd.DatetimeIndex(batch.column(0).to_pandas())
                position = index.searchsorted(target)
                if position < len(index):
                    return offset+int(position)
                offset += len(index)
        raise ValueError("Requested window starts after source end")



def history_capacity_preflight(source, cadence_seconds, config=None, ceiling_rows=HISTORY_COMPATIBILITY_CEILING_ROWS):
    """Compute exact row capacity for the frozen fixed-time feature window using timestamps only."""
    config = config or FeatureConfig()
    duration_seconds = cadence_seconds * config.window_samples * max(config.scales)
    duration_ns = int(round(duration_seconds * 1e9))
    history = np.empty(0, dtype=np.int64)
    max_window_rows = max_retained_rows = scanned_rows = 0
    for index in source.timestamp_batches():
        times = index.as_unit("ns").asi8
        if not len(times): continue
        if len(history) and times[0] <= history[-1]:
            raise ValueError("History preflight requires strictly increasing timestamps")
        combined = np.concatenate([history, times])
        offset = len(history)
        starts = np.searchsorted(combined, times-duration_ns, side="left")
        ends = np.arange(offset, offset+len(times), dtype=np.int64)
        widths = ends-starts
        if len(widths): max_window_rows = max(max_window_rows, int(widths.max()))
        keep_at = int(np.searchsorted(combined, times[-1]-duration_ns, side="left"))
        history = combined[keep_at:].copy()
        max_retained_rows = max(max_retained_rows, len(history))
        scanned_rows += len(times)
    exact_required = max(max_window_rows, max_retained_rows)
    required = max(config.max_history_rows, exact_required)
    approved = required <= ceiling_rows
    return {
        "status": "approved" if approved else "unsupported_resource_ceiling",
        "mode": HISTORY_COMPATIBILITY["mode"],
        "initial_cadence_seconds": float(cadence_seconds),
        "longest_fixed_window_seconds": float(duration_seconds),
        "frozen_default_guard_rows": int(config.max_history_rows),
        "exact_required_rows": int(exact_required),
        "approved_cap_rows": int(required) if approved else int(config.max_history_rows),
        "ceiling_rows": int(ceiling_rows),
        "timestamp_rows_scanned": int(scanned_rows),
        "feature_math_changed": False, "resampling": False, "labels_used": False, "values_used": False,
        "decision": ("Exact fixed-time legacy feature window enabled with an audited engineering history budget" if approved else
                     "Legacy comparators must abstain because exact fixed-time history exceeds the declared resource ceiling"),
    }


def _legacy_feature_config(history_compatibility):
    base = LEGACY_COMPARATOR_FEATURE_CONFIG
    return FeatureConfig(
        window_samples=base.window_samples,
        scales=tuple(base.scales),
        min_periods=base.min_periods,
        epsilon=base.epsilon,
        score_cap=base.score_cap,
        max_history_rows=int(history_compatibility["approved_cap_rows"]),
        block_size=base.block_size,
    )

def _assert_legacy_builder_contract(builder, history_compatibility):
    expected = _legacy_feature_config(history_compatibility)
    actual = builder.config
    fields = ("window_samples", "scales", "min_periods", "epsilon",
              "score_cap", "max_history_rows", "block_size")
    mismatches = {
        name: {"expected": getattr(expected, name), "actual": getattr(actual, name)}
        for name in fields
        if getattr(expected, name) != getattr(actual, name)
    }
    if mismatches:
        raise RuntimeError(
            "M1.3 legacy feature-builder contract drift: "
            + json.dumps(mismatches, default=str, sort_keys=True)
        )
    return actual

def _legacy(state, raw):
    if state.get("legacy_failed"):
        return None
    _assert_legacy_builder_contract(state["builder"], state["history_compatibility"])
    try:
        return state["builder"].transform(raw)
    except ValueError as exc:
        if "max_history_rows" not in str(exc):
            raise
        state["legacy_failed"] = True
        for name in ("robust_statistical", "isolation_forest"):
            state["unsupported"][name] = {"status": "unsupported", "reason": str(exc),
                "at": raw.index[0].isoformat(), "no_silent_history_cap_change": True}
        return None


def _timed(state, name, call):
    started = time.perf_counter()
    try:
        return call()
    finally:
        state["timings"][name] = state["timings"].get(name, 0.) + time.perf_counter()-started


def _scores(state, raw, timing):
    temporal = state["temporal"].score(raw, timing.cadence_seconds.to_numpy())
    flags = state["policy"].apply(temporal)
    ratio = np.maximum(temporal.point_score/state["point_cal"].threshold,
                       temporal.interval_score/state["interval_cal"].threshold)
    predictions = pd.DataFrame({"value": raw}, index=raw.index)
    legacy = _legacy(state, raw)
    stat = state["stat"].score(legacy) if legacy is not None else None
    iso = state["iso"].score(legacy) if legacy is not None and state.get("iso") is not None else None
    candidates = {
        "temporal_point": (flags.point_flag, temporal.point_score),
        "temporal_interval": (flags.interval_flag, temporal.interval_score),
        "improved_temporal": (flags.temporal_flag, ratio),
    }
    if stat is not None:
        candidates["robust_statistical"] = (stat.statistical_flag, stat.statistical_score)

    # M1.3.1 operator policy: only calibrated temporal evidence can create an
    # operator-facing combined incident. Isolation Forest remains a comparator.
    combined_flags = temporal_first_operator_flags(flags.temporal_flag)
    combined_scores = np.fmax(
        temporal.point_score/state["point_cal"].threshold,
        temporal.interval_score/state["interval_cal"].threshold,
    )
    candidates["combined"] = (combined_flags, combined_scores)

    if iso is not None:
        candidates["isolation_forest"] = (iso.iforest_flag, iso.iforest_score)
    events = []
    for name in MODELS:
        present = name in candidates and name not in state["unsupported"]
        flags_, scores = candidates[name] if present else (np.zeros(len(raw), bool), np.full(len(raw), np.nan))
        predictions[name+"_flag"], predictions[name+"_score"] = np.asarray(flags_), np.asarray(scores)
        if present:
            grouper = state["groupers"][name]
            completed = grouper.update(
                raw.index, flags_, scores, timing.cadence_seconds.to_numpy(), name,
                evidence={"score_semantics": "candidate-specific score; not a probability"})
            finalized = grouper.take_finalization_times()
            if len(finalized) != len(completed):
                raise RuntimeError("Event finalization metadata is misaligned")
            events.extend(
                {"model": name, "_finalized_at": when, **event}
                for event, when in zip(completed, finalized)
            )
            state["coverage"][name] += len(raw)
    predictions = predictions.join(temporal.add_prefix("temporal_feature_")).join(timing.add_prefix("timing_"))
    state["truncated"] += int(temporal.truncated_history.sum())
    state["stale"] += int(temporal.point_reference_stale.sum())
    return predictions, events


def _test_gaps(state, gaps, channel, split):
    result = []
    for gap in gaps:
        if pd.Timestamp(gap["start"]) >= pd.Timestamp(split["test_start"]) and pd.Timestamp(gap["end"]) <= pd.Timestamp(split["test_end"]):
            result.append({"model": "adaptive_gap", **gap, "channel": channel,
                "evidence": {"cause": "unknown", "resolved_at": gap["resolved_at"], "resolution": gap["resolution"]}})
    return result


def _canonical_event_order(events, fallback_timestamp):
    """Order completed events independently of the outer scoring batch size."""
    fallback = pd.Timestamp(fallback_timestamp)
    ordered = []
    for event in events:
        item = dict(event)
        finalized = item.pop("_finalized_at", None)
        if finalized is None and isinstance(item.get("evidence"), dict):
            finalized = item["evidence"].get("resolved_at")
        if finalized is None:
            finalized = fallback
        key = (
            pd.Timestamp(finalized).value,
            str(item.get("model", "")),
            pd.Timestamp(item["start"]).value,
            pd.Timestamp(item["end"]).value,
        )
        ordered.append((key, item))
    ordered.sort(key=lambda pair: pair[0])
    return [item for _, item in ordered]


def run_channel(path, output, channel, annotation_provider, *, labelled_channel=True,
                base_row=0, rows=None, batch_size=5000, scope="synthetic", expected_sha256=None,
                train_fraction=.6, validation_fraction=.2, fault=None):
    """One independent channel; caller supplies an explicit A/B/synthetic plan."""
    output = Path(output).resolve()
    if scope not in {"A", "B", "synthetic"}:
        raise ValueError("Scope must explicitly identify A, B or synthetic")
    if scope == "B" and (train_fraction != .6 or validation_fraction != .2):
        raise ValueError("B requires the frozen 60/20/20 protocol")
    source = ParquetChannel(path, base_row, rows, batch_size, expected_sha256)
    split = source.split(train_fraction, validation_fraction)
    a, b = split["train_stop"], split["validation_stop"]
    initial_index = pd.DatetimeIndex(np.concatenate([s.index.as_unit("ns").asi8 for s in source.batches(0, min(a, 10001))]), tz="UTC")
    initial = training_cadence(initial_index)
    history_compatibility = history_capacity_preflight(source, initial, config=LEGACY_COMPARATOR_FEATURE_CONFIG)
    config = {"channel": channel, "base_row": base_row, "rows": source.rows, "batch_size": batch_size,
              "scope": scope, "split": split, "labelled_channel": labelled_channel,
              "history_compatibility": history_compatibility,
              "legacy_comparator_feature_config": asdict(LEGACY_COMPARATOR_FEATURE_CONFIG)}
    identities = {"source": source.sha256, "code": code_identity(), "config": fingerprint(config), "protocol": fingerprint(PROTOCOL)}
    with run_lock(output):
        journal = FragmentJournal(output/"journal", identities, fault)
        state = journal.load()
        if state is not None and state["stage"] == "done":
            report = json.loads((output/"report.json").read_text())
            if fingerprint(report) != state["report_fingerprint"]:
                raise ValueError("Completed report corrupted")
            return report
        if state is None:
            unsupported = {}
            legacy_failed = history_compatibility["status"] != "approved"
            if legacy_failed:
                for name in ("robust_statistical", "isolation_forest"):
                    unsupported[name] = {"status": "unsupported",
                        "reason": "Exact frozen feature history exceeds declared compatibility resource ceiling",
                        "history_compatibility": history_compatibility, "no_silent_history_cap_change": True}
            state = {"stage": "statistics", "cursor": 0, "timings": {}, "unsupported": unsupported,
                     "initial": initial, "history_compatibility": history_compatibility, "legacy_failed": legacy_failed,
                     "coverage": {name: 0 for name in MODELS}, "truncated": 0, "stale": 0}
            atomic_json(output/"history_compatibility.json", history_compatibility)
            atomic_json(output/"run_configuration.json", {"identities": identities, "configuration": config, "protocol": PROTOCOL})
            journal.commit(state)

        def commit(**kwargs):
            return _timed(state, "checkpoint", lambda: journal.commit(state, **kwargs))

        with ResourceMonitor() as monitor:
            try:
                if state["stage"] == "statistics":
                    state["temporal"] = _timed(state, "statistics", lambda: fit_temporal_stream(
                        lambda: source.batches(0, a), output/"scratch", train_end=split["train_end"]))
                    feature_config = FeatureConfig(max_history_rows=int(state["history_compatibility"]["approved_cap_rows"]))
                    state.update(stage="train_features", cursor=0, builder=TemporalFeatureBuilder(state["initial"], _legacy_feature_config(state["history_compatibility"])),
                                 sampler=BoundedTrainingSampler(10000, 42, split["train_end"]),
                                 stat_sampler=BoundedTrainingSampler(20000, 42, split["train_end"]))
                    commit()
                if state["stage"] == "train_features":
                    for raw in source.batches(state["cursor"], a):
                        features = _timed(state, "feature_extraction", lambda: _legacy(state, raw))
                        if features is not None:
                            state["sampler"].update(features.loc[_valid(features), ["value", "value_change", "robust_score", "dispersion", "gap_ratio"]])
                            state["stat_sampler"].update(features.loc[_valid(features), ["robust_score"]].dropna())
                        state["cursor"] += len(raw)
                        commit()
                    state.update(stage="fit_models")
                    commit()
                if state["stage"] == "fit_models":
                    state["stat"] = StatisticalDetector(6.)
                    state["stat"]._training = state["stat_sampler"].metadata()
                    state["iso"] = None
                    if not state.get("legacy_failed"):
                        try:
                            state["iso"] = _timed(state, "model_fitting", lambda: IsolationForestDetector(
                                seed=42, max_train_rows=10000, n_estimators=100, batch_size=batch_size).fit(
                                    state["sampler"].sample(), train_end=split["train_end"]))
                            state["iso"]._training = state["sampler"].metadata()
                        except ValueError as exc:
                            for name in ("isolation_forest",):
                                state["unsupported"][name] = {"status": "unsupported", "reason": str(exc)}
                    del state["sampler"], state["stat_sampler"]
                    state.update(stage="prefix", cursor=0, tracker=SamplingRegimeTracker(state["initial"]))
                    commit()
                if state["stage"] == "prefix":
                    # Split each pass at training boundary: legacy builder is already at train end.
                    for end in (a, b):
                        if state["cursor"] >= end:
                            continue
                        for raw in source.batches(state["cursor"], end):
                            timing = _timed(state, "cadence", lambda: state["tracker"].transform(raw.index))
                            temporal = _timed(state, "prefix_scoring", lambda: state["temporal"].score(raw, timing.cadence_seconds.to_numpy()))
                            if state["cursor"] >= a:
                                _timed(state, "feature_extraction", lambda: _legacy(state, raw))
                            state["tracker"].drain_gaps()
                            state["cursor"] += len(raw)
                            commit(frames={"prefix": temporal.join(timing.add_prefix("timing_"))})
                    state.update(stage="calibration")
                    commit()
                if state["stage"] == "calibration":
                    def scores(column):
                        for _, frame in journal.frames("prefix"):
                            selected = frame.loc[(frame.index >= pd.Timestamp(split["validation_start"])) &
                                                 (frame.index <= pd.Timestamp(split["validation_end"])), column]
                            if len(selected):
                                yield selected
                    for name in ("point", "interval"):
                        state[name+"_cal"] = _timed(state, "calibration", lambda name=name: calibrate_stream(
                            lambda: scores(name+"_score"), output/"scratch", validation_end=split["validation_end"]))
                    state["policy"] = DetectionPolicy(state["point_cal"].threshold, state["interval_cal"].threshold, 3, .5)
                    for _, frame in journal.frames("prefix"):
                        _timed(state, "policy_warmup", lambda: state["policy"].apply(frame))
                    frozen = {"identities": identities, "split": split, "protocol": PROTOCOL,
                              "fit_identity": fingerprint({"identities": identities, "temporal": state["temporal"].metadata(),
                                                           "point": state["point_cal"].metadata(), "interval": state["interval_cal"].metadata()}),
                              "temporal": state["temporal"].metadata(), "statistical": state["stat"].metadata(),
                              "isolation_forest": state["iso"].metadata() if state["iso"] is not None else None,
                              "calibration": {name: state[name+"_cal"].metadata() for name in ("point", "interval")},
                              "legacy_features": state["builder"].metadata(), "history_compatibility": state["history_compatibility"],
                              "labels_used_for_training_or_calibration": False, "operator_policy": operator_policy_metadata(), "unsupported": state["unsupported"].copy()}
                    state["frozen"] = frozen
                    state["groupers"] = {name: StreamingTemporalEventGrouper(channel, 1.5 if name in MODELS[:2] else 2.) for name in MODELS}
                    state.update(stage="test", cursor=b)
                    commit(json_values={"model_configuration": frozen})
                if state["stage"] == "test":
                    for raw in source.batches(state["cursor"]):
                        timing = _timed(state, "cadence", lambda: state["tracker"].transform(raw.index))
                        predictions, events = _timed(state, "scoring", lambda: _scores(state, raw, timing))
                        events += _test_gaps(state, state["tracker"].drain_gaps(), channel, split)
                        events = _canonical_event_order(events, raw.index[-1])
                        state["cursor"] += len(raw)
                        commit(frames={"predictions": predictions}, events=events)
                    events = []
                    for name, grouper in state["groupers"].items():
                        if name not in state["unsupported"]:
                            completed = grouper.finish()
                            finalized = grouper.take_finalization_times()
                            if len(finalized) != len(completed):
                                raise RuntimeError("Final event ordering metadata is misaligned")
                            events += [
                                {"model": name, "_finalized_at": when, **event}
                                for event, when in zip(completed, finalized)
                            ]
                    events += _test_gaps(state, state["tracker"].finish(), channel, split)
                    events = _canonical_event_order(events, split["test_end"])
                    state.update(stage="prepare_evaluation")
                    commit(events=events)
                if state["stage"] == "prepare_evaluation":
                    from app.streaming_evaluation import StreamingPointEnvelopes, StreamingScientificEvaluator
                    ann = annotation_provider()  # Scoring and fitting are complete before labels enter evaluation.
                    envelopes = StreamingPointEnvelopes(ann)
                    for kind in ("prefix", "predictions"):
                        for _, frame in journal.frames(kind):
                            _timed(state, "evaluation", lambda: envelopes.update(frame.timing_cadence_seconds))
                    prepared = envelopes.finish()
                    state["evaluators"] = {name: StreamingScientificEvaluator(prepared, split["test_start"], split["test_end"],
                        labelled_channel=labelled_channel, gap_task=name=="adaptive_gap",
                        expected_rows=split["test_rows"]).to_state()
                        for name in (*MODELS, "adaptive_gap") if name not in state["unsupported"]}
                    state.update(stage="evaluation_samples", evaluation_generation=-1,
                                 scoring_last_generation=journal.pointer["generation"])
                    commit()
                if state["stage"] == "evaluation_samples":
                    from app.streaming_evaluation import StreamingScientificEvaluator
                    evaluators = {name: StreamingScientificEvaluator.from_state(data) for name, data in state["evaluators"].items()}
                    for generation, frame in journal.frames("predictions", state["scoring_last_generation"]):
                        if generation <= state["evaluation_generation"]:
                            continue
                        timing = frame.filter(regex="^timing_").rename(columns=lambda name: name.removeprefix("timing_"))
                        for name, evaluator in evaluators.items():
                            flags = np.zeros(len(frame), bool) if name=="adaptive_gap" else frame[name+"_flag"]
                            _timed(state, "evaluation", lambda: evaluator.update_samples(frame.index, flags, timing))
                        state["evaluators"] = {name: evaluator.to_state() for name, evaluator in evaluators.items()}
                        state["evaluation_generation"] = generation
                        commit()
                    state.update(stage="evaluation_events", evaluation_generation=-1)
                    commit()
                if state["stage"] == "evaluation_events":
                    from app.streaming_evaluation import StreamingScientificEvaluator
                    evaluators = {name: StreamingScientificEvaluator.from_state(data) for name, data in state["evaluators"].items()}
                    for generation, path_, _ in journal.fragments("events", state["scoring_last_generation"]):
                        if generation <= state["evaluation_generation"]:
                            continue
                        correlated = []
                        with path_.open(encoding="utf-8") as stream:
                            for line in stream:
                                event = json.loads(line)
                                if event["model"] in evaluators:
                                    correlated.append({"model": event["model"], **_timed(state, "evaluation", lambda: evaluators[event["model"]].update_event(event))})
                        state["evaluators"] = {name: evaluator.to_state() for name, evaluator in evaluators.items()}
                        state["evaluation_generation"] = generation
                        commit(json_values={"correlated_events": correlated})
                    report = {"channel": channel, "scope": scope, "split": split, "status": "completed" if not state["unsupported"] else "completed_with_unsupported_comparators",
                              "identities": identities, "frozen": state["frozen"], "models": {name: ev.result() for name, ev in evaluators.items() if name!="adaptive_gap"},
                              "communication_gaps": evaluators["adaptive_gap"].result(), "unsupported_comparators": state["unsupported"],
                              "comparator_scored_rows": state["coverage"], "history_truncation_rows": state["truncated"], "post_gap_test_rows": state["stale"],
                              "history_compatibility": state["history_compatibility"],
                              "stage_seconds": state["timings"], "regimes": state["tracker"].regimes(),
                              "events_storage": "journal immutable events and correlated_events fragments",
                              "random_forest": {"status": "unsupported", "reason": "No independently confirmed negative training labels"},
                              "pca": {"status": "unsupported", "reason": "Separate declared paired alignment plan required"}}
                    from app.streaming_evaluation import _plain
                    report = _plain(report)
                    state.update(stage="done", report_fingerprint=fingerprint(report))
                    atomic_json(output/"report.json", report)
                    commit(json_values={"report": report})
            except BaseException as exc:
                atomic_json(output/"last_failure.json", {"at": utc_now(), "stage": state["stage"], "cursor": state.get("cursor"),
                    "error": f"{type(exc).__name__}: {exc}", "recovery": "Resume from last committed generation; no append"})
                raise
        execution = {"completed_at": utc_now(), "resources": monitor.measurements, "read_seconds": source.read_seconds,
                     "decoded_rows": source.rows_read, "read_rows_per_second": source.rows_read/source.read_seconds if source.read_seconds else None,
                     "history_preflight_timestamp_rows": source.timestamp_rows_read,
                     "history_preflight_timestamp_read_seconds": source.timestamp_read_seconds,
                     "storage": journal.storage_metrics(), "checkpoint_seconds_this_attempt": journal.commit_seconds,
                     "statistics_resources": state["temporal"].streaming_resources,
                     "calibration_resources": {name: state[name+"_cal"].streaming_resources for name in ("point", "interval")}}
        atomic_json(output/"execution.json", execution)
        return report


def prepare_execution_plan(dataset, store, output, m12_protocol):
    """Materialize exact B boundaries and exposure checks without fitting."""
    dataset, store, output = Path(dataset).resolve(), Path(store).resolve(), Path(output).resolve()
    protocol_path = Path(m12_protocol).resolve()
    manifest_path = store/"manifest.json"
    integrity_path = store.parent/"integrity/integrity_report.json"
    baseline_path = store.parent.parent/"milestone13/baseline_verification.json"
    manifest = json.loads(manifest_path.read_text())
    integrity = json.loads(integrity_path.read_text())
    m12 = json.loads(protocol_path.read_text())
    if integrity.get("status") != "verified" or integrity.get("verified_channel_count") != 76:
        raise ValueError("Verified M1.2 all-channel integrity is required")
    if file_sha256(manifest_path) != integrity.get("ingestion_manifest_sha256"):
        raise ValueError("M1.2 ingestion manifest differs from integrity evidence")
    if baseline_path.exists() and json.loads(baseline_path.read_text()).get("status") != "verified":
        raise ValueError("M1.3 immutable baseline verification failed")
    exposed = {}
    for name, window in m12["dataset_A"]["raw_windows"].items():
        exposed.setdefault(window["channel"], []).append({"name": name,
            "start": window["start_inclusive"], "end": window["end_inclusive"]})
    catalog = pd.read_csv(dataset/"channels.csv").set_index("Channel")
    entries = {}
    for channel in sorted(manifest["channels"], key=lambda value: int(value.split("_")[-1])):
        entry = manifest["channels"][channel]
        if entry.get("status") != "completed" or file_sha256(entry["path"]) != entry["file_sha256"]:
            raise ValueError(f"{channel}: verified completed Parquet is required")
        source = ParquetChannel(entry["path"], batch_size=5000, expected_sha256=entry["file_sha256"])
        split = source.split()
        intersections = [window for window in exposed.get(channel, []) if
            pd.Timestamp(window["start"]) <= pd.Timestamp(split["test_end"]) and
            pd.Timestamp(window["end"]) >= pd.Timestamp(split["test_start"])]
        entries[channel] = {"channel": channel, "dataset": "B2_later_window" if channel in exposed else "B1_other_channel",
            "target": str(catalog.loc[channel, "Target"]), "rows": source.rows, "base_row": 0,
            "split": split, "parquet_path": str(source.path), "parquet_sha256": source.sha256,
            "source_identity": entry["source"], "A_test_intersections": intersections,
            "status": "exposure_overlap_requires_plan" if intersections else "ready_after_review"}
    if any(entry["A_test_intersections"] for entry in entries.values()):
        plan_status = "blocked_by_exposure_overlap"
    else:
        plan_status = "pending_explicit_review"
    payload = {"schema_version": 1, "dataset_fingerprint": manifest["dataset"]["fingerprint"],
        "ingestion_manifest_sha256": file_sha256(manifest_path), "integrity_report_sha256": file_sha256(integrity_path),
        "m12_protocol_sha256": file_sha256(protocol_path), "annotation_sha256": {
            name: file_sha256(dataset/name) for name in ("labels.csv", "anomaly_types.csv")},
        "runner_code_identity": code_identity(), "protocol": PROTOCOL, "worker_count": 1,
        "scoring_batch_rows": 5000, "channels": entries,
        "interpretation": "Retrospective B evaluation under a frozen procedure; not external blind validation"}
    plan_id = fingerprint(payload)
    plan = {"created_at": utc_now(), "status": plan_status, "execution_authorized": False,
        "benchmark_executed": False, "plan_id": plan_id, "payload": payload,
        "review": {"status": "pending", "approved_plan_id": None, "reviewed_at": None,
                   "reviewer": None, "note": "Explicit review is required before any full benchmark execution"}}
    atomic_json(output, plan)
    return plan


def _validate_approved_plan(plan):
    if fingerprint(plan.get("payload")) != plan.get("plan_id"):
        raise ValueError("Execution plan payload changed after creation")
    review = plan.get("review", {})
    if (not plan.get("execution_authorized") or review.get("status") != "approved" or
            review.get("approved_plan_id") != plan.get("plan_id") or not review.get("reviewed_at") or
            not str(review.get("reviewer", "")).strip()):
        raise PermissionError("Full benchmark plan requires explicit recorded review and authorization")
    if plan["payload"]["runner_code_identity"] != code_identity():
        raise ValueError("Runner code changed after plan review; create and review a new plan")


def run_approved_plan(dataset, plan_path, output, channels=None):
    """Future reviewed entry point. M1.3 creates but does not authorize its plan."""
    dataset, plan_path, output = Path(dataset).resolve(), Path(plan_path).resolve(), Path(output).resolve()
    plan = json.loads(plan_path.read_text())
    _validate_approved_plan(plan)
    planned = plan["payload"]["channels"]
    selected = list(planned) if channels is None else [str(channel) if str(channel).startswith("channel_") else f"channel_{int(channel)}" for channel in channels]
    unknown = set(selected)-set(planned)
    if unknown:
        raise ValueError(f"Channels absent from reviewed plan: {sorted(unknown)}")
    catalog = pd.read_csv(dataset/"channels.csv").set_index("Channel")
    manifest_path = output/"manifest.json"
    with run_lock(output):
        run_manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {
            "created_at": utc_now(), "plan_id": plan["plan_id"], "channels": {}, "status": "running"}
        if run_manifest["plan_id"] != plan["plan_id"]:
            raise ValueError("Output namespace belongs to another reviewed plan")
        for channel in selected:
            item = planned[channel]
            if item["status"] != "ready_after_review":
                raise ValueError(f"{channel}: plan status is {item['status']}")
            def provider(channel=channel):
                labels = pd.read_csv(dataset/"labels.csv")
                types = pd.read_csv(dataset/"anomaly_types.csv")
                return annotations(labels, types, channel)
            report = run_channel(item["parquet_path"], output/"B"/channel, channel, provider,
                labelled_channel=str(catalog.loc[channel, "Target"]) == "YES", base_row=item["base_row"],
                rows=item["rows"], batch_size=plan["payload"]["scoring_batch_rows"], scope="B",
                expected_sha256=item["parquet_sha256"])
            run_manifest["channels"][channel] = {"status": report["status"], "report": str(output/"B"/channel/"report.json")}
            atomic_json(manifest_path, run_manifest)
        run_manifest.update(status="completed" if set(selected)==set(planned) else "partial_reviewed_execution",
                            updated_at=utc_now())
        atomic_json(manifest_path, run_manifest)
    return run_manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="Prepare an unapproved exact 76-channel execution plan")
    plan.add_argument("--dataset", default="../data/esa_adb/mission1/ESA-Mission1")
    plan.add_argument("--store", type=Path, default=Path("../artifacts/milestone12/telemetry"))
    plan.add_argument("--m12-protocol", type=Path, default=Path("../artifacts/milestone12/benchmark_protocol.json"))
    plan.add_argument("--output", type=Path, default=Path("../artifacts/milestone13/execution_plan.json"))
    run = sub.add_parser("run", help="Execute only an explicitly reviewed plan")
    run.add_argument("--dataset", default="../data/esa_adb/mission1/ESA-Mission1")
    run.add_argument("--plan", type=Path, default=Path("../artifacts/milestone13/execution_plan.json"))
    run.add_argument("--output", type=Path, default=Path("../artifacts/milestone13/benchmark"))
    run.add_argument("--channels", nargs="*")
    args = parser.parse_args()
    dataset = resolve_dataset(args.dataset)
    result = (prepare_execution_plan(dataset, args.store, args.output, args.m12_protocol)
              if args.command == "plan" else run_approved_plan(dataset, args.plan, args.output, args.channels))
    print(json.dumps({key: result.get(key) for key in ("status", "plan_id", "execution_authorized", "benchmark_executed")}, default=str))


if __name__ == "__main__":
    main()
