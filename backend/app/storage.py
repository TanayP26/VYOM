"""Read-only ESA archive ingestion and bounded Parquet access.

Pickle is not a streaming format: ingestion necessarily materializes ONE trusted
local archive. All validation, Arrow conversion, and later reads use bounded
chunks. Sources are never rewritten. Timestamps must be valid, ordered and
unique; ambiguous input is rejected rather than silently repaired.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import gc
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Iterator
from zipfile import ZipFile

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

LOGGER = logging.getLogger(__name__)
FORMAT_VERSION = 1
VALIDATION_CHUNK = 250_000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, payload: dict) -> None:
    """Replace a JSON artifact only after its complete contents reach disk."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def _store_lock(directory: Path):
    """An OS-managed lock survives stale lock files but not stale processes."""
    lock = directory / ".ingestion.lock"
    with lock.open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError(f"Another ingestion owns {directory}") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _output(root: Path, output: Path) -> tuple[Path, Path]:
    root, output = Path(root).resolve(), Path(output).resolve()
    if not (root / "channels.csv").is_file():
        raise FileNotFoundError(f"Dataset has no channels.csv: {root}")
    if output == root or root in output.parents:
        raise ValueError("Derived artifacts must be outside the original dataset directory")
    output.mkdir(parents=True, exist_ok=True)
    return root, output


def _channel_name(channel: str) -> str:
    value = str(channel)
    if value.isdecimal():
        value = f"channel_{int(value)}"
    if not re.fullmatch(r"channel_[1-9][0-9]*", value):
        raise ValueError(f"Invalid channel identifier: {value!r}")
    return value


def _catalog(root: Path) -> pd.DataFrame:
    catalog = pd.read_csv(root / "channels.csv")
    if "Channel" not in catalog or catalog.Channel.duplicated().any():
        raise ValueError("channels.csv requires unique Channel identifiers")
    catalog["Channel"] = catalog.Channel.map(_channel_name)
    return catalog


def _selection(catalog: pd.DataFrame, channels) -> list[str]:
    selected = catalog.Channel.tolist() if channels is None else [_channel_name(c) for c in channels]
    unknown = set(selected) - set(catalog.Channel)
    if unknown:
        raise ValueError(f"Channels absent from metadata: {sorted(unknown)}")
    if len(set(selected)) != len(selected):
        raise ValueError("Channel selection contains duplicates")
    return selected


def _archive_identity(path: Path) -> dict:
    stat = path.stat()
    with ZipFile(path) as archive:
        members = [member for member in archive.infolist() if not member.is_dir()]
        if len(members) != 1:
            raise ValueError(f"{path.name}: expected exactly one pickle member")
        member = members[0]
        return {"name": path.name, "size_bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns, "member": member.filename,
                "uncompressed_bytes": member.file_size, "crc32": member.CRC}


def dataset_identity(root: Path) -> dict:
    """Metadata SHA256 plus ZIP CRC/size/mtime identity; not a cryptographic data audit."""
    root = Path(root).resolve()
    metadata_hashes = {}
    for name in ("channels.csv", "labels.csv", "anomaly_types.csv", "telecommands.csv"):
        path = root / name
        if path.exists():
            metadata_hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    sources = {c: _archive_identity(root / "channels" / f"{c}.zip")
               for c in _catalog(root).Channel}
    digest = hashlib.sha256(json.dumps({"metadata": metadata_hashes, "sources": sources},
                                       sort_keys=True).encode()).hexdigest()
    return {"name": "ESA-ADB Mission 1", "root": str(root), "fingerprint": digest,
            "fingerprint_method": "metadata SHA256 and archive ZIP CRC32, size, mtime_ns",
            "metadata_sha256": metadata_hashes, "sources": sources}


def estimate_cadence(index: pd.DatetimeIndex, max_samples: int = 100_000) -> dict:
    """Median positive adjacent delta using a deterministic evenly spread sample."""
    if max_samples < 1:
        raise ValueError("max_samples must be positive")
    if len(index) < 2:
        return {"seconds": None, "method": "median adjacent delta", "sampled_deltas": 0}
    positions = np.linspace(1, len(index) - 1, min(max_samples, len(index) - 1), dtype=np.int64)
    ns = index.as_unit("ns").asi8
    deltas = (ns[positions] - ns[positions - 1]).astype(np.float64) / 1e9
    positive = deltas[deltas > 0]
    if len(positive) == 0:
        raise ValueError("No positive timestamp deltas available to estimate cadence")
    return {"seconds": float(np.median(positive)), "method": "median positive adjacent delta; evenly spaced deterministic sample",
            "sampled_deltas": len(positive), "total_deltas": len(index) - 1,
            "sample_min_seconds": float(positive.min()),
            "sample_p10_seconds": float(np.quantile(positive, .1)),
            "sample_p90_seconds": float(np.quantile(positive, .9)),
            "sample_max_seconds": float(positive.max())}


def _load_validated(root: Path, channel: str) -> tuple[pd.DataFrame, dict]:
    path = root / "channels" / f"{channel}.zip"
    with ZipFile(path) as archive:
        members = [m for m in archive.infolist() if not m.is_dir()]
        if len(members) != 1:
            raise ValueError(f"{channel}: expected exactly one pickle member")
        # Pickle execution is intentional: only the user's trusted ESA dataset belongs here.
        with archive.open(members[0]) as stream:
            frame = pd.read_pickle(stream)
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError(f"{channel}: expected a nonempty pandas DataFrame")
    if not isinstance(frame.index, pd.DatetimeIndex):
        candidate = [c for c in frame.columns if str(c).lower() in {"time", "timestamp", "datetime", "date"}]
        if len(candidate) != 1:
            raise ValueError(f"{channel}: expected a DatetimeIndex or exactly one timestamp column")
        timestamps = pd.to_datetime(frame.pop(candidate[0]), utc=True, errors="raise")
        frame.index = pd.DatetimeIndex(timestamps)
    naive_timestamps = frame.index.tz is None
    frame.index = pd.to_datetime(frame.index, utc=True).as_unit("ns")
    frame.index.name = "timestamp"
    if frame.index.hasnans:
        raise ValueError(f"{channel}: invalid or missing timestamps")
    if not frame.columns.is_unique or not all(isinstance(c, str) for c in frame.columns):
        raise ValueError(f"{channel}: telemetry column names must be unique strings")
    if "timestamp" in frame.columns or not len(frame.columns):
        raise ValueError(f"{channel}: invalid telemetry schema")
    for column, dtype in frame.dtypes.items():
        if not pd.api.types.is_numeric_dtype(dtype) or pd.api.types.is_bool_dtype(dtype) or pd.api.types.is_complex_dtype(dtype):
            raise ValueError(f"{channel}.{column}: expected real numeric telemetry, found {dtype}")
    missing = {c: 0 for c in frame}
    minima, maxima = {c: None for c in frame}, {c: None for c in frame}
    previous = None
    for start in range(0, len(frame), VALIDATION_CHUNK):
        chunk = frame.iloc[start:start + VALIDATION_CHUNK]
        ns = chunk.index.asi8
        differences = np.diff(ns)
        if np.any(differences == 0) or (previous is not None and ns[0] == previous):
            raise ValueError(f"{channel}: duplicate timestamps; explicit source correction required")
        if np.any(differences < 0) or (previous is not None and ns[0] < previous):
            raise ValueError(f"{channel}: timestamps are not monotonically increasing")
        previous = ns[-1]
        for column in chunk:
            values = chunk[column].to_numpy(dtype=None, na_value=np.nan)
            if np.isinf(values).any():
                raise ValueError(f"{channel}.{column}: infinite numeric values are invalid")
            missing[column] += int(pd.isna(values).sum())
            if len(values) > pd.isna(values).sum():
                low, high = float(np.nanmin(values)), float(np.nanmax(values))
                minima[column] = low if minima[column] is None else min(minima[column], low)
                maxima[column] = high if maxima[column] is None else max(maxima[column], high)
    cadence = estimate_cadence(frame.index)
    profile = {"channel": channel, "rows": len(frame), "start": frame.index[0].isoformat(),
               "end": frame.index[-1].isoformat(), "cadence_seconds": cadence["seconds"],
               "cadence_estimate": cadence, "schema": {c: str(t) for c, t in frame.dtypes.items()},
               "timestamp_schema": "timestamp[ns, UTC]", "naive_source_assumed_utc": naive_timestamps,
               "missing_values": missing,
               "missing_percent": {c: 100 * n / len(frame) for c, n in missing.items()},
               "minimum": minima, "maximum": maxima, "duplicate_timestamps": 0,
               "validation_policy": "reject invalid/infinite/non-numeric/duplicate/unordered; preserve NaN",
               "dataframe_bytes": int(frame.memory_usage(index=True, deep=True).sum())}
    return frame, profile


def _arrow_table(frame: pd.DataFrame) -> pa.Table:
    arrays = {"timestamp": pa.array(frame.index, type=pa.timestamp("ns", tz="UTC"))}
    arrays.update({c: pa.array(frame[c], from_pandas=True) for c in frame})
    return pa.table(arrays)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _valid_artifact(entry: dict) -> bool:
    try:
        path = Path(entry["path"])
        if path.stat().st_size != entry["file_size_bytes"]:
            return False
        with pq.ParquetFile(path) as parquet:
            if parquet.metadata.num_rows != entry["rows"]:
                return False
        return _file_sha256(path) == entry["file_sha256"]
    except (OSError, KeyError, pa.ArrowException):
        return False


def ingest_dataset(root: Path, output: Path, channels=None, force: bool = False,
                   row_group_size: int = 250_000) -> dict:
    """Ingest selected channels, resuming at channel granularity after interruption."""
    if row_group_size < 1:
        raise ValueError("row_group_size must be positive")
    root, output = _output(root, output)
    selected = _selection(_catalog(root), channels)
    identity = dataset_identity(root)
    manifest_path = output / "manifest.json"
    config = {"row_group_size": row_group_size, "format_version": FORMAT_VERSION,
              "compression": "zstd", "validation": "strict-v1"}
    with _store_lock(output):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {
            "created_at": _now(), "channels": {}, "format_version": FORMAT_VERSION}
        old_root = manifest.get("dataset", {}).get("root")
        if old_root and old_root != str(root):
            raise ValueError("Store belongs to a different source dataset; use a separate output directory")
        # Previously ingested channels cannot remain current when their source changed,
        # even when this invocation requests only another channel.
        for channel, entry in manifest["channels"].items():
            if entry.get("source") != identity["sources"].get(channel):
                entry.update(status="stale", stale_reason="Source fingerprint changed")
        manifest.update(dataset=identity, config=config, status="running", updated_at=_now(), selected_channels=selected)
        atomic_json(manifest_path, manifest)
        for position, channel in enumerate(selected, 1):
            entry = manifest["channels"].get(channel, {})
            source = identity["sources"][channel]
            if not force and entry.get("status") == "completed" and entry.get("source") == source and entry.get("config") == config and _valid_artifact(entry):
                LOGGER.info("ingestion_skipped", extra={"channel": channel, "position": position, "total": len(selected)})
                continue
            started = time.perf_counter()
            destination = output / f"{channel}.parquet"
            temporary = output / f".{channel}.parquet.partial"
            manifest["channels"][channel] = {"channel": channel, "status": "running", "started_at": _now(), "source": source, "config": config}
            atomic_json(manifest_path, manifest)
            frame = None
            try:
                frame, profile = _load_validated(root, channel)
                with pq.ParquetWriter(temporary, _arrow_table(frame.iloc[:0]).schema, compression="zstd") as writer:
                    for offset in range(0, len(frame), row_group_size):
                        writer.write_table(_arrow_table(frame.iloc[offset:offset + row_group_size]), row_group_size=row_group_size)
                if _archive_identity(root / "channels" / f"{channel}.zip") != source:
                    raise RuntimeError(f"{channel}: source changed during ingestion; retry from a stable dataset")
                with temporary.open("r+b") as stream:
                    os.fsync(stream.fileno())
                os.replace(temporary, destination)
                manifest["channels"][channel].update(profile, path=str(destination),
                    file_size_bytes=destination.stat().st_size, file_sha256=_file_sha256(destination),
                    status="completed", completed_at=_now(),
                    elapsed_seconds=time.perf_counter() - started)
                LOGGER.info("ingestion_completed", extra={"channel": channel, "rows": len(frame), "position": position, "total": len(selected)})
            except BaseException as exc:
                status = "failed" if isinstance(exc, Exception) else "interrupted"
                manifest["channels"][channel].update(
                    status=status, error=f"{type(exc).__name__}: {exc}",
                    **{f"{status}_at": _now()})
                manifest.update(status=status, updated_at=_now())
                atomic_json(manifest_path, manifest)
                raise
            finally:
                del frame
                gc.collect()
            manifest["updated_at"] = _now()
            atomic_json(manifest_path, manifest)
        manifest.update(status="completed", updated_at=_now(),
                        channel_coverage={"available": len(identity["sources"]),
                                          "completed": sum(e.get("status") == "completed" for e in manifest["channels"].values()),
                                          "requested": len(selected)})
        atomic_json(manifest_path, manifest)
        return manifest


def profile_dataset(root: Path, output: Path, channels=None) -> dict:
    """Profile every selected archive without generating Parquet or modifying sources."""
    root, output = _output(root, output)
    catalog = _catalog(root)
    selected = _selection(catalog, channels)
    identity = dataset_identity(root)
    report_path = output / "dataset_profile.json"
    report = {"dataset": identity, "created_at": _now(), "status": "running",
              "coverage": {"available": len(catalog), "requested": len(selected), "profiled": 0},
              "channels": {}, "compressed_bytes": sum(s["size_bytes"] for s in identity["sources"].values()),
              "uncompressed_bytes": sum(s["uncompressed_bytes"] for s in identity["sources"].values())}
    for row in catalog.to_dict("records"):
        report["channels"][row["Channel"]] = {"metadata": {k: None if pd.isna(v) else v for k, v in row.items()},
                                              "source": identity["sources"][row["Channel"]], "status": "not_profiled"}
    if "Target" in catalog:
        report["target_channels"] = {str(k): int(v) for k, v in catalog.Target.value_counts().items()}
    labels_file, types_file = root / "labels.csv", root / "anomaly_types.csv"
    if labels_file.exists() and types_file.exists():
        labels, types = pd.read_csv(labels_file), pd.read_csv(types_file)
        labels["StartTime"] = pd.to_datetime(labels.StartTime, utc=True, errors="raise")
        labels["EndTime"] = pd.to_datetime(labels.EndTime, utc=True, errors="raise")
        joined = labels.merge(types[["ID", "Category"]], on="ID", how="left", validate="many_to_one")
        report["annotations"] = {"records": len(labels), "definitions": len(types),
            "point_events": int((labels.StartTime == labels.EndTime).sum()),
            "invalid_intervals": int((labels.StartTime.isna() | labels.EndTime.isna() | (labels.StartTime > labels.EndTime)).sum()),
            "unmatched_ids": int(joined.Category.isna().sum()),
            "categories": {str(k): int(v) for k, v in joined.Category.value_counts().items()}}
        if "Target" in catalog:
            target_by_channel = catalog.set_index("Channel").Target
            report["annotations"]["records_not_on_target_yes"] = int((labels.Channel.map(target_by_channel) != "YES").sum())
    atomic_json(report_path, report)
    for position, channel in enumerate(selected, 1):
        started = time.perf_counter()
        frame = None
        try:
            frame, detail = _load_validated(root, channel)
            if _archive_identity(root / "channels" / f"{channel}.zip") != identity["sources"][channel]:
                raise RuntimeError(f"{channel}: source changed during profiling")
            report["channels"][channel].update(detail, status="completed", elapsed_seconds=time.perf_counter() - started)
            report["coverage"]["profiled"] += 1
            LOGGER.info("profile_completed", extra={"channel": channel, "position": position, "total": len(selected), "rows": len(frame)})
        except Exception as exc:
            report["channels"][channel].update(status="failed", error=f"{type(exc).__name__}: {exc}")
            LOGGER.exception("profile_failed", extra={"channel": channel})
        finally:
            del frame
            gc.collect()
        atomic_json(report_path, report)
    report.update(status="completed" if report["coverage"]["profiled"] == len(selected) else "failed", completed_at=_now())
    atomic_json(report_path, report)
    return report


def iter_channel_batches(store: Path, channel: str, batch_size: int = 25_000,
                         start=None, end=None, max_rows: int | None = None) -> Iterator[pd.DataFrame]:
    """Read bounded batches with inclusive UTC bounds; no whole-column materialization."""
    if batch_size < 1 or (max_rows is not None and max_rows < 1):
        raise ValueError("batch_size and max_rows must be positive")
    store = Path(store).resolve()
    channel = _channel_name(channel)
    manifest = json.loads((store / "manifest.json").read_text(encoding="utf-8"))
    entry = manifest["channels"].get(channel, {})
    if entry.get("status") != "completed":
        raise ValueError(f"{channel}: no successfully ingested artifact")
    path = Path(entry["path"]).resolve()
    if path.parent != store:
        raise ValueError("Manifest points outside the expected Parquet store")
    lower = pd.to_datetime(start, utc=True) if start is not None else None
    upper = pd.to_datetime(end, utc=True) if end is not None else None
    if lower is not None and upper is not None and lower > upper:
        raise ValueError("start must be at or before end")
    with pq.ParquetFile(path) as parquet:
        timestamp_column = parquet.schema_arrow.get_field_index("timestamp")
        remaining = max_rows
        for group in range(parquet.num_row_groups):
            stats = parquet.metadata.row_group(group).column(timestamp_column).statistics
            if stats is not None and stats.has_min_max:
                if lower is not None and pd.to_datetime(stats.max, utc=True) < lower:
                    continue
                if upper is not None and pd.to_datetime(stats.min, utc=True) > upper:
                    break
            for batch in parquet.iter_batches(batch_size=batch_size, row_groups=[group]):
                frame = batch.to_pandas().set_index("timestamp")
                if lower is not None:
                    frame = frame.loc[frame.index >= lower]
                if upper is not None:
                    frame = frame.loc[frame.index <= upper]
                if remaining is not None:
                    frame = frame.iloc[:remaining]
                    remaining -= len(frame)
                if not frame.empty:
                    yield frame
                if remaining == 0:
                    return
