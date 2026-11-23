from __future__ import annotations
from functools import lru_cache
from pathlib import Path
import json
import numpy as np
import pandas as pd

from app.core import settings

REQUIRED = {
    "channels.csv": ["Channel", "Subsystem", "Physical Unit", "Group", "Target"],
    "labels.csv": ["ID", "Channel", "StartTime", "EndTime"],
    "anomaly_types.csv": ["ID", "Category", "Class", "Subclass"],
    "telecommands.csv": ["Telecommand", "Priority"],
}


def dataset_root() -> Path:
    cfg = settings()
    candidates = [Path(cfg.dataset_dir), Path.cwd()/cfg.dataset_dir, Path.cwd().parent/cfg.dataset_dir]
    for p in candidates:
        p = p.expanduser().resolve()
        if (p / "channels.csv").is_file():
            return p
    raise FileNotFoundError(f"ESA Mission 1 dataset not found. Set DATASET_DIR; checked {cfg.dataset_dir}")

@lru_cache(maxsize=1)
def metadata() -> dict[str, pd.DataFrame]:
    root = dataset_root()
    result: dict[str, pd.DataFrame] = {}
    for name, cols in REQUIRED.items():
        frame = pd.read_csv(root/name)
        missing = set(cols)-set(frame.columns)
        if missing:
            raise ValueError(f"{name} missing columns {sorted(missing)}")
        result[name[:-4]] = frame
    labels = result["labels"]
    types = result["anomaly_types"]
    labels["ID"] = labels.ID.astype(str); types["ID"] = types.ID.astype(str)
    labels["StartTime"] = pd.to_datetime(labels.StartTime, utc=True, errors="raise")
    labels["EndTime"] = pd.to_datetime(labels.EndTime, utc=True, errors="raise")
    if (labels.StartTime > labels.EndTime).any():
        raise ValueError("Reversed annotation interval")
    return result


def channel_annotations(channel: str) -> pd.DataFrame:
    m = metadata()
    labels = m["labels"][m["labels"].Channel.astype(str) == str(channel)]
    return labels.merge(m["anomaly_types"][["ID","Category","Class","Subclass"]], on="ID", how="left", validate="many_to_one")


def store_root() -> Path:
    p = settings().resolve(settings().telemetry_store_dir)
    if not p.exists():
        raise FileNotFoundError(f"Telemetry Parquet store not found: {p}. Run M1.2 ingestion or point TELEMETRY_STORE_DIR to it.")
    return p


def _manifest() -> dict:
    path = store_root()/"manifest.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def channel_parquet(channel: str) -> Path:
    manifest = _manifest()
    entry = (manifest.get("channels") or {}).get(channel)
    if entry:
        p = Path(entry.get("path", ""))
        if not p.is_absolute():
            p = (store_root()/p).resolve()
        if p.is_file(): return p
    guesses = [store_root()/f"{channel}.parquet", store_root()/channel/f"{channel}.parquet", store_root()/channel/"telemetry.parquet"]
    for p in guesses:
        if p.is_file(): return p
    raise FileNotFoundError(f"No Parquet file registered for {channel}")


def channel_catalog() -> list[dict]:
    channels = metadata()["channels"].copy()
    counts = metadata()["labels"].Channel.value_counts()
    manifest = _manifest().get("channels", {})
    rows = []
    for r in channels.to_dict("records"):
        name = str(r["Channel"])
        e = manifest.get(name, {})
        rows.append({
            "channel": name,
            "subsystem": r["Subsystem"],
            "physical_unit": r["Physical Unit"],
            "group": int(r["Group"]),
            "target": str(r["Target"]),
            "annotation_count": int(counts.get(name, 0)),
            "rows": int(e.get("rows", e.get("row_count", 0)) or 0),
            "ingested": bool(e),
        })
    return rows


def mission_summary() -> dict:
    m = metadata(); labels = m["labels"]; channels = m["channels"]
    cats = labels.merge(m["anomaly_types"][["ID","Category"]], on="ID", how="left").Category.value_counts().to_dict()
    cat = channel_catalog()
    return {
        "mission": "ESA Mission 1",
        "channels": len(channels),
        "target_channels": int((channels.Target.astype(str)=="YES").sum()),
        "context_channels": int((channels.Target.astype(str)=="NO").sum()),
        "annotations": len(labels),
        "point_annotations": int((labels.StartTime==labels.EndTime).sum()),
        "categories": {str(k): int(v) for k,v in cats.items()},
        "ingested_channels": sum(x["ingested"] for x in cat),
        "observations": int(sum(x["rows"] for x in cat)),
        "scientific_note": "Target=NO is contextual/unlabelled; it is never treated as a supervised normal class.",
    }
