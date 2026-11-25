"""Prepare/verify a complete VYOM data snapshot. Never upload to Git.
Run prepare from backend with its existing virtual environment and .env.
Run verify inside the isolated cloud service before enabling serve mode.
"""
import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "backend"))
sys.path.insert(0, str(BASE))
EXPECTED_ROWS = 744856895
EXPECTED_RUNS = {10: ("channel_12", 31308), 11: ("channel_13", 7747)}
INDEX = "migration_inventory.json"
READY = "migration_verified.json"

def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def inventory(root):
    items = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Unexpected symlink: {path}")
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            if relative in {INDEX, READY}:
                continue
            items[relative] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
    return items

def verify_science(root):
    import pandas as pd
    import pyarrow.parquet as pq
    catalog = pd.read_csv(root / "dataset/channels.csv")
    channels = catalog["Channel"].astype(str).tolist()
    if len(channels) != 76 or len(set(channels)) != 76:
        raise ValueError("Expected 76 unique source channels")
    for name in ("channels.csv", "labels.csv", "anomaly_types.csv", "telecommands.csv"):
        if not (root / "dataset" / name).is_file():
            raise ValueError(f"Missing source metadata: {name}")
    if len(pd.read_csv(root / "dataset/labels.csv")) != 3589:
        raise ValueError("Annotation count differs from evaluated dataset")
    manifest = json.loads((root / "telemetry/manifest.json").read_text(encoding="utf-8"))
    entries = manifest.get("channels", {})
    if set(entries) != set(channels):
        raise ValueError("Parquet catalog differs from source catalog")
    total = 0
    for ch in channels:
        if not (root / "dataset/channels" / f"{ch}.zip").is_file():
            raise ValueError(f"Missing source archive: {ch}")
        path = root / "telemetry" / f"{ch}.parquet"
        if not path.is_file():
            raise ValueError(f"Missing Parquet: {ch}")
        with pq.ParquetFile(path) as parquet:
            rows = parquet.metadata.num_rows
        expected = int(entries[ch].get("rows", entries[ch].get("row_count", 0)))
        if rows != expected:
            raise ValueError(f"Parquet row count mismatch: {ch}")
        total += rows
    if total != EXPECTED_ROWS:
        raise ValueError(f"Expected {EXPECTED_ROWS} rows, got {total}")
    # Immutable prevents any writes, including temporary WAL/SHM files, during verification.
    with sqlite3.connect((root / "vyom.db").resolve().as_uri() + "?mode=ro&immutable=1", uri=True) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite integrity check failed")
        if db.execute("SELECT count(*) FROM analysis_runs WHERE status IN ('queued','running')").fetchone()[0]:
            raise ValueError("Snapshot contains active runs; stop VYOM and resolve run state")
        for run, (ch, expected) in EXPECTED_RUNS.items():
            record = db.execute("SELECT status FROM analysis_runs WHERE id=?", (run,)).fetchone()
            if not record or record[0] != "completed":
                raise ValueError(f"Missing completed Run {run}")
            count = db.execute("SELECT count(*) FROM detection_events WHERE run_id=?", (run,)).fetchone()[0]
            if count != expected:
                raise ValueError(f"Run {run}: expected {expected} incidents, got {count}")
            directory = root / "reports" / f"run_{run:05d}" / ch
            result = json.loads((directory / "product_summary.json").read_text(encoding="utf-8"))
            if result.get("incidents", result.get("events")) != expected:
                raise ValueError(f"Run {run} report count mismatch")
            if not (directory / "report.json").is_file():
                raise ValueError(f"Missing scientific report for Run {run}")
    return {"channels": len(channels), "observations": total, "run_counts": {str(k): v[1] for k, v in EXPECTED_RUNS.items()}}

def prepare(target):
    from app.core import settings
    from sqlalchemy.engine import make_url
    cfg = settings()
    url = make_url(cfg.database_url)
    if not url.drivername.startswith("sqlite") or not url.database or url.database == ":memory:":
        raise ValueError("Expected the native SQLite database")
    source_db = cfg.resolve(url.database)
    sources = {"dataset": cfg.resolve(cfg.dataset_dir), "telemetry": cfg.resolve(cfg.telemetry_store_dir),
               "reports": cfg.resolve(cfg.artifact_dir)}
    for name, source in sources.items():
        if not source.is_dir():
            raise FileNotFoundError(f"Missing {name}: {source}")
    if not source_db.is_file():
        raise FileNotFoundError(source_db)
    target = target.resolve()
    if target.exists():
        raise FileExistsError("Choose a new snapshot directory; existing snapshots are never overwritten")
    if BASE in target.parents or target == BASE:
        raise ValueError("Snapshot must be outside the Git repository")
    if any(source == target or source in target.parents for source in sources.values()):
        raise ValueError("Snapshot cannot be inside a source directory")
    size = sum(p.stat().st_size for source in sources.values() for p in source.rglob("*") if p.is_file()) + source_db.stat().st_size
    print(f"Source snapshot bytes: {size:,}")
    if shutil.disk_usage(target.parent).free < size + 1024**3:
        raise RuntimeError("Insufficient local free space for an independent snapshot")
    target.mkdir()
    for name, source in sources.items():
        print(f"Copying {name}...", flush=True)
        shutil.copytree(source, target / name)
    # Consistent independent backup. No writes to the source database.
    with sqlite3.connect(source_db.as_uri() + "?mode=ro", uri=True) as original:
        with sqlite3.connect(target / "vyom.db") as copy:
            original.backup(copy)
    # Avoid uploading secrets accidentally present among data/artifacts.
    for p in target.rglob("*"):
        if p.is_file() and (p.name == ".env" or p.name.startswith(".env.") or p.suffix.lower() in {".key", ".pem"}):
            raise ValueError(f"Review potentially sensitive file before upload: {p}")
    science = verify_science(target)
    print("Hashing snapshot files...", flush=True)
    entries = inventory(target)
    payload = {"format": 1, "science": science, "files": entries,
               "total_bytes": sum(x["bytes"] for x in entries.values())}
    (target / INDEX).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in payload.items() if k != "files"}, indent=2))

def verify(root, mark_ready):
    root = root.resolve()
    if mark_ready and root != Path("/vyom-data"):
        raise ValueError("Readiness marker is only written on the cloud volume")
    if (root / READY).exists():
        raise ValueError("Existing readiness marker: do not overwrite an accepted snapshot")
    expected = json.loads((root / INDEX).read_text(encoding="utf-8"))
    if expected.get("format") != 1:
        raise ValueError("Unsupported migration inventory")
    actual = inventory(root)
    if actual != expected["files"]:
        bad = sorted(k for k in set(actual) | set(expected["files"]) if actual.get(k) != expected["files"].get(k))
        raise ValueError("Missing, extra or corrupt files: " + ", ".join(bad[:20]))
    science = verify_science(root)
    if science != expected["science"]:
        raise ValueError("Scientific inventory differs")
    result = {"status": "verified", **science, "files": len(actual),
              "total_bytes": expected["total_bytes"], "inventory_sha256": sha256(root / INDEX)}
    if mark_ready:
        with (root / READY).open("x", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("prepare")
    p.add_argument("directory", type=Path)
    v = commands.add_parser("verify")
    v.add_argument("directory", type=Path)
    v.add_argument("--mark-ready", action="store_true")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.directory)
    else:
        verify(args.directory, args.mark_ready)
