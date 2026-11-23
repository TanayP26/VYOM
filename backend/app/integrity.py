"""Read-only, all-row source-to-Parquet verification with resumable evidence.

One trusted source pickle must be materialized because pickle is not a row-stream
format. The Parquet side is read in bounded batches. No model or database code
is imported, and source archives are never rewritten.
"""
from __future__ import annotations

import gc
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from app.artifacts import ResourceMonitor, file_sha256, fingerprint, run_lock, utc_now
from app.storage import _catalog, _channel_name, _load_validated, _store_lock, atomic_json, dataset_identity

LOG = logging.getLogger(__name__)
REPORT_VERSION = 1


def _input_failure(report_path, message):
    report = {"status": "failed", "completed_at": utc_now(), "channels": {},
              "verified_channel_count": 0, "verified_rows": 0, "errors": [message],
              "all_rows_compared_exactly": False, "all_source_archives_sha256_unchanged": False}
    atomic_json(report_path, report)
    return report


def _read_metadata(path):
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict) or not isinstance(result.get("channels"), dict):
        raise ValueError(f"{path.name}: expected a JSON object with a channels mapping")
    if any(not isinstance(entry, dict) for entry in result["channels"].values()):
        raise ValueError(f"{path.name}: channel entries must be JSON objects")
    return result


def _same_numeric_values(actual, expected):
    """Require exact finite representations, including signed zero, and NaN masks.

    Parquet represents pandas NaN as null, so NaN payload bits are intentionally
    not a preservation contract. All finite float32 bits are checked exactly.
    """
    actual, expected = np.asarray(actual), np.asarray(expected)
    if actual.dtype != expected.dtype or actual.shape != expected.shape:
        return False
    missing_actual, missing_expected = pd.isna(actual), pd.isna(expected)
    if not np.array_equal(missing_actual, missing_expected):
        return False
    keep = ~missing_actual
    actual, expected = np.ascontiguousarray(actual[keep]), np.ascontiguousarray(expected[keep])
    return actual.tobytes() == expected.tobytes()


def _verify_channel(root, store, channel, entry, profile_entry, batch_size):
    path = Path(entry["path"]).resolve()
    if path.parent != store or path.name != f"{channel}.parquet":
        raise ValueError("Parquet path does not preserve the expected channel identity")
    frame, source = _load_validated(root, channel)
    parquet = None
    try:
        parquet = pq.ParquetFile(path)
        schema = parquet.schema_arrow
        timestamp = schema.field("timestamp")
        if not pa.types.is_timestamp(timestamp.type) or timestamp.type.unit != "ns" or timestamp.type.tz != "UTC":
            raise ValueError("Parquet timestamp schema must be timestamp[ns, UTC]")
        expected_columns = ["timestamp", *frame.columns]
        if schema.names != expected_columns:
            raise ValueError(f"Parquet schema columns differ from source: {schema.names} != {expected_columns}")
        if parquet.metadata.num_rows != len(frame) or entry.get("rows") != len(frame):
            raise ValueError("Manifest/Parquet row count differs from the original source")
        if entry.get("channel") != channel:
            raise ValueError("Manifest channel identity does not match catalog/path")
        for field in ("rows", "start", "end", "schema", "timestamp_schema", "missing_values", "minimum", "maximum", "duplicate_timestamps"):
            if entry.get(field) != source[field]:
                raise ValueError(f"Manifest {field} differs from original source")
            if profile_entry is not None and profile_entry.get(field) != source[field]:
                raise ValueError(f"Preserved source profile {field} differs from original source")
        rows = 0
        previous = None
        first, last = None, None
        missing = {name: 0 for name in frame.columns}
        minima = {name: None for name in frame.columns}
        maxima = dict(minima)
        groups = parquet.num_row_groups
        for batch in parquet.iter_batches(batch_size=batch_size):
            actual = batch.to_pandas()
            times = pd.DatetimeIndex(actual.pop("timestamp"))
            if times.hasnans:
                raise ValueError("Parquet contains missing timestamps")
            ns = times.as_unit("ns").asi8
            differences = np.diff(ns)
            if np.any(differences == 0) or (previous is not None and ns[0] == previous):
                raise ValueError("Parquet contains duplicate timestamps")
            if np.any(differences < 0) or (previous is not None and ns[0] < previous):
                raise ValueError("Parquet timestamps are not strictly ordered")
            previous = ns[-1]
            first = times[0] if first is None else first
            last = times[-1]
            expected = frame.iloc[rows:rows+len(actual)]
            if len(expected) != len(actual) or not np.array_equal(ns, expected.index.asi8):
                raise ValueError(f"Source-to-Parquet timestamp mismatch at batch starting row {rows}")
            for name in frame.columns:
                values = actual[name].to_numpy()
                original = expected[name].to_numpy()
                if actual[name].dtype != frame[name].dtype:
                    raise ValueError(f"Numeric dtype differs from original source for {name}")
                if not pd.api.types.is_numeric_dtype(actual[name]) or np.isinf(values).any():
                    raise ValueError(f"Invalid numeric Parquet data for {name}")
                if not _same_numeric_values(values, original):
                    raise ValueError(f"Source-to-Parquet value mismatch for {name} at batch starting row {rows}")
                nulls = pd.isna(values)
                missing[name] += int(nulls.sum())
                if (~nulls).any():
                    low, high = float(values[~nulls].min()), float(values[~nulls].max())
                    minima[name] = low if minima[name] is None else min(minima[name], low)
                    maxima[name] = high if maxima[name] is None else max(maxima[name], high)
            rows += len(actual)
        if rows != len(frame):
            raise ValueError("Decoded Parquet row count differs from original source")
        if missing != source["missing_values"] or minima != source["minimum"] or maxima != source["maximum"]:
            raise ValueError("Parquet value statistics differ from original source")
        return {"channel": channel, "rows": rows, "start": first.isoformat(), "end": last.isoformat(),
                "schema": source["schema"], "timestamp_schema": "timestamp[ns, UTC]",
                "missing_values": missing, "minimum": minima, "maximum": maxima,
                "timestamp_ordering": "strictly_increasing", "duplicate_timestamps": 0,
                "invalid_timestamps": 0, "infinite_values": 0,
                "row_groups": groups, "largest_row_group": max(parquet.metadata.row_group(i).num_rows for i in range(groups)),
                "source_to_parquet_all_timestamps_equal": True,
                "source_to_parquet_all_values_equal": True,
                "comparison": "all rows; exact UTC nanoseconds, numeric dtype, finite value bits and NaN masks",
                "source_profile_checked": profile_entry is not None}
    finally:
        if parquet is not None:
            parquet.close()
        del frame
        gc.collect()


def verify_dataset(root, store, output, profile_path=None, expected_channels=None,
                   expected_rows=None, batch_size=250000, before_channel=None):
    """Verify a complete catalog and return atomic machine-readable evidence.

    Validation failures return a report with status='failed'; unexpected process
    interruptions are checkpointed and re-raised. Completed channel comparisons
    are reused only after source/Parquet SHA256 and their metadata still match.
    A resume hashes all source archives and Parquet files again; it never trusts
    an mtime-only match. Set expected_channels=76 and expected_rows=744856895 for
    the actual Mission1 delivery; synthetic test datasets may be smaller.
    An optional before_channel(channel) resource gate runs before any per-channel
    reads. If it raises, the interruption is checkpointed and propagated without
    moving on to another channel.
    """
    root, store, output = Path(root).resolve(), Path(store).resolve(), Path(output).resolve()
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if any(output == path or path in output.parents or output in path.parents for path in (root, store)):
        raise ValueError("Integrity output must be outside and separate from source/store paths")
    if not store.is_dir():
        raise FileNotFoundError(store)
    profile_path = Path(profile_path).resolve() if profile_path else None
    try:
        catalog = _catalog(root).Channel.tolist()
    except Exception as exc:
        with run_lock(output):
            return _input_failure(output / "integrity_report.json", f"Invalid source catalog: {type(exc).__name__}: {exc}")
    if expected_channels is None or isinstance(expected_channels, int):
        expected = catalog
        expected_count = len(catalog) if expected_channels is None else expected_channels
    else:
        expected = [_channel_name(str(channel)) for channel in expected_channels]
        expected_count = len(expected)
    if len(set(expected)) != len(expected):
        raise ValueError("Expected channel names must be unique")
    with run_lock(output), _store_lock(store):
        report_path = output / "integrity_report.json"
        manifest_path = store / "manifest.json"
        try:
            prior = _read_metadata(report_path) if report_path.exists() else {}
            source_identity = dataset_identity(root)
            manifest = _read_metadata(manifest_path)
            manifest_hash = file_sha256(manifest_path)
            profile = _read_metadata(profile_path) if profile_path else None
        except Exception as exc:
            return _input_failure(report_path, f"Invalid verification input: {type(exc).__name__}: {exc}")
        config = {"report_version": REPORT_VERSION, "source": str(root), "store": str(store),
                  "expected_channels": expected, "expected_count": expected_count,
                  "expected_rows": expected_rows, "batch_size": batch_size,
                  "profile_sha256": file_sha256(profile_path) if profile_path else None,
                  "verifier_sha256": file_sha256(__file__)}
        report = {"created_at": prior.get("created_at", utc_now()), "started_at": utc_now(),
                  "status": "running", "configuration": config,
                  "dataset": source_identity, "ingestion_manifest_sha256": manifest_hash,
                  "expected_channel_count": expected_count, "channels": {}, "errors": [],
                  "original_rows_basis": "fresh original pickle comparison plus preserved full-source profile" if profile else "fresh original pickle comparison",
                  "memory_contract": "one trusted source pickle plus one bounded Parquet batch; never the full dataset"}
        errors = report["errors"]
        if len(catalog) != expected_count or set(catalog) != set(expected):
            errors.append("Catalog does not match the expected channel set/count")
        entries = manifest.get("channels", {})
        if set(entries) != set(expected):
            errors.append("Ingestion manifest must contain exactly the expected channel set")
        artifacts = {path.stem for path in store.glob("*.parquet")}
        if artifacts != set(expected):
            errors.append("Parquet files must contain exactly the expected channel set")
        if manifest.get("status") != "completed" or any(entry.get("status") != "completed" for entry in entries.values()):
            errors.append("Ingestion manifest is not completely finished")
        if manifest.get("dataset") != source_identity:
            errors.append("Current source identity differs from the ingestion dataset identity")
        if profile is not None:
            if profile.get("status") != "completed" or set(profile.get("channels", {})) != set(expected):
                errors.append("Source profile does not cover exactly the completed expected channels")
            if profile.get("dataset") != source_identity:
                errors.append("Preserved source profile identity differs from the current source")
            counts = [entry.get("rows") for entry in profile.get("channels", {}).values()]
            if any(not isinstance(count, int) or isinstance(count, bool) or count < 0 for count in counts):
                errors.append("Source profile row counts must be nonnegative integers")
            profile_rows = sum(count for count in counts if isinstance(count, int))
            report["profile_total_rows"] = profile_rows
            if expected_rows is not None and profile_rows != expected_rows:
                errors.append("Preserved source-profile total differs from required observation count")
        atomic_json(report_path, report)
        if errors:
            report.update(status="failed", completed_at=utc_now(), verified_channel_count=0, verified_rows=0)
            atomic_json(report_path, report)
            return report
        resumed = 0
        with ResourceMonitor() as total_monitor:
            for position, channel in enumerate(expected, 1):
                entry = entries[channel]
                source_path = root / "channels" / f"{channel}.zip"
                detail = {"channel": channel, "status": "running", "started_at": utc_now()}
                report["channels"][channel] = detail
                atomic_json(report_path, report)
                if before_channel is not None:
                    try:
                        before_channel(channel)
                    except BaseException as exc:
                        detail.update(status="interrupted", stage="before_channel", error=f"{type(exc).__name__}: {exc}")
                        report.update(status="interrupted", interrupted_at=utc_now())
                        atomic_json(report_path, report)
                        raise
                try:
                    with ResourceMonitor() as channel_monitor:
                        parquet_path = Path(entry["path"]).resolve()
                        if parquet_path.parent != store or parquet_path.name != f"{channel}.parquet":
                            raise ValueError("Manifest path points outside the expected channel artifact")
                        if entry.get("source") != source_identity["sources"][channel]:
                            raise ValueError("Manifest channel source identity differs from current source")
                        source_sha, parquet_sha = file_sha256(source_path), file_sha256(parquet_path)
                        if parquet_sha != entry.get("file_sha256") or parquet_path.stat().st_size != entry.get("file_size_bytes"):
                            raise ValueError("Parquet SHA256/size does not match completed ingestion manifest")
                        profile_entry = profile["channels"][channel] if profile else None
                        verification_id = fingerprint({"configuration": config, "source_sha256": source_sha,
                            "parquet_sha256": parquet_sha, "manifest_entry": entry, "profile_entry": profile_entry})
                        old = prior.get("channels", {}).get(channel, {})
                        if old.get("status") == "verified" and old.get("verification_id") == verification_id:
                            detail.update(old, resumed=True, hash_rechecked_at=utc_now())
                            resumed += 1
                            LOG.info("integrity_verified_resume channel=%s position=%d/%d", channel, position, len(expected))
                        else:
                            detail.update(_verify_channel(root, store, channel, entry, profile_entry, batch_size))
                            detail.update(status="verified", completed_at=utc_now(), resumed=False,
                                source_sha256_before=source_sha, source_sha256_after=source_sha,
                                parquet_sha256_before=parquet_sha, parquet_sha256_after=parquet_sha,
                                verification_id=verification_id, source_archive_unchanged=True)
                            LOG.info("integrity_verified channel=%s rows=%d position=%d/%d", channel, detail["rows"], position, len(expected))
                        if file_sha256(source_path) != source_sha:
                            raise ValueError("Original archive changed during verification")
                        if file_sha256(parquet_path) != parquet_sha:
                            raise ValueError("Parquet file changed during verification")
                    detail["last_execution_resources"] = channel_monitor.measurements
                    if not detail["resumed"]:
                        detail["full_comparison_resources"] = channel_monitor.measurements
                except Exception as exc:
                    detail.update(status="failed", error=f"{type(exc).__name__}: {exc}", failed_at=utc_now())
                    errors.append(f"{channel}: {detail['error']}")
                    LOG.exception("integrity_failed channel=%s", channel)
                except BaseException as exc:
                    detail.update(status="interrupted", error=f"{type(exc).__name__}: {exc}")
                    report.update(status="interrupted", interrupted_at=utc_now())
                    atomic_json(report_path, report)
                    raise
                atomic_json(report_path, report)
        verified = [entry for entry in report["channels"].values() if entry["status"] == "verified"]
        rows = sum(entry["rows"] for entry in verified)
        if expected_rows is not None and rows != expected_rows:
            errors.append(f"Verified observation count {rows} differs from required {expected_rows}")
        if file_sha256(manifest_path) != manifest_hash:
            errors.append("Ingestion manifest changed during verification")
        if dataset_identity(root) != source_identity:
            errors.append("Dataset identity changed during verification")
        report.update(status="verified" if not errors and len(verified) == expected_count else "failed",
            completed_at=utc_now(), verified_channel_count=len(verified), verified_rows=rows,
            resumed_channel_count=resumed, resources=total_monitor.measurements,
            all_source_archives_sha256_unchanged=all(entry.get("source_archive_unchanged", False) for entry in verified) and len(verified) == expected_count,
            all_rows_compared_exactly=not errors and len(verified) == expected_count)
        atomic_json(report_path, report)
        return report
