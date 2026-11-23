from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from app.storage import (dataset_identity, estimate_cadence, ingest_dataset,
                         iter_channel_batches, profile_dataset)


def archive(root, channel, frame):
    stream = BytesIO()
    frame.to_pickle(stream)
    with ZipFile(root / "channels" / f"{channel}.zip", "w", ZIP_DEFLATED) as zipped:
        zipped.writestr(f"{channel}.pkl", stream.getvalue())


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    (root / "channels").mkdir(parents=True)
    pd.DataFrame({"Channel": ["channel_1", "channel_2"], "Target": ["YES", "NO"]}).to_csv(root / "channels.csv", index=False)
    for number, cadence in ((1, "30s"), (2, "15min")):
        frame = pd.DataFrame({"value": np.arange(23, dtype=np.float32)},
                             index=pd.date_range("2001-01-01", periods=23, freq=cadence))
        archive(root, f"channel_{number}", frame)
    pd.DataFrame({"ID": ["id_1", "id_2"], "Channel": ["channel_1", "channel_1"],
                  "StartTime": ["2001-01-01", "2001-01-02"], "EndTime": ["2001-01-01", "2001-01-03"]}).to_csv(root / "labels.csv", index=False)
    pd.DataFrame({"ID": ["id_1", "id_2"], "Category": ["Rare Event", "Communication Gap"]}).to_csv(root / "anomaly_types.csv", index=False)
    return root


def test_parquet_round_trip_preserves_timestamps_float32_and_bounds(source, tmp_path):
    store = tmp_path / "store"
    before = dataset_identity(source)
    result = ingest_dataset(source, store, row_group_size=7)
    assert result["channel_coverage"] == {"available": 2, "completed": 2, "requested": 2}
    assert result["channels"]["channel_1"]["cadence_seconds"] == 30
    assert result["channels"]["channel_2"]["cadence_seconds"] == 900
    assert dataset_identity(source) == before
    parquet = pq.ParquetFile(result["channels"]["channel_1"]["path"])
    assert parquet.num_row_groups == 4
    assert all(parquet.metadata.row_group(n).num_rows <= 7 for n in range(4))
    batches = list(iter_channel_batches(store, "channel_1", batch_size=4,
                                        start="2001-01-01T00:01:00Z", end="2001-01-01T00:04:00Z", max_rows=5))
    assert max(map(len, batches)) <= 4
    data = pd.concat(batches)
    assert len(data) == 5
    assert str(data.index.tz) == "UTC"
    assert data.index[0] == pd.Timestamp("2001-01-01T00:01:00Z")
    assert data.value.dtype == np.float32
    assert data.value.tolist() == [2, 3, 4, 5, 6]


def test_ingestion_skips_completed_and_resumes_interrupted(source, tmp_path):
    store = tmp_path / "store"
    first = ingest_dataset(source, store, channels=["channel_1"], row_group_size=7)
    artifact = Path(first["channels"]["channel_1"]["path"])
    first_time = artifact.stat().st_mtime_ns
    result = ingest_dataset(source, store, row_group_size=7)
    assert artifact.stat().st_mtime_ns == first_time
    assert result["channel_coverage"]["completed"] == 2
    # Simulate an interrupted channel: its partial artifact must not be reused.
    result["channels"]["channel_2"]["status"] = "running"
    (store / "manifest.json").write_text(json.dumps(result), encoding="utf-8")
    (store / ".channel_2.parquet.partial").write_bytes(b"interrupted")
    resumed = ingest_dataset(source, store, row_group_size=7)
    assert resumed["channels"]["channel_2"]["status"] == "completed"
    assert not (store / ".channel_2.parquet.partial").exists()
    assert artifact.stat().st_mtime_ns == first_time


def test_force_and_source_changes_reingest(source, tmp_path):
    store = tmp_path / "store"
    first = ingest_dataset(source, store, channels=["channel_1"])
    first_time = first["channels"]["channel_1"]["completed_at"]
    forced = ingest_dataset(source, store, channels=["channel_1"], force=True)
    assert forced["channels"]["channel_1"]["completed_at"] != first_time
    frame = pd.DataFrame({"value": np.arange(10, dtype=np.float32)}, index=pd.date_range("2002-01-01", periods=10, freq="3s"))
    archive(source, "channel_1", frame)
    changed = ingest_dataset(source, store, channels=["channel_1"])
    assert changed["channels"]["channel_1"]["rows"] == 10
    assert changed["channels"]["channel_1"]["cadence_seconds"] == 3


@pytest.mark.parametrize("kind, message", [("duplicate", "duplicate"), ("disordered", "monotonically"),
                                           ("infinite", "infinite"), ("nonnumeric", "numeric"), ("nat", "missing timestamps")])
def test_invalid_input_is_rejected_without_repair(source, tmp_path, kind, message):
    index = pd.date_range("2001-01-01", periods=3, freq="min")
    values = np.array([1, 2, 3], dtype=np.float32)
    if kind == "duplicate":
        index = pd.DatetimeIndex([index[0], index[0], index[2]])
    elif kind == "disordered":
        index = index[::-1]
    elif kind == "nat":
        index = pd.DatetimeIndex([index[0], pd.NaT, index[2]])
    elif kind == "infinite":
        values[1] = np.inf
    elif kind == "nonnumeric":
        values = ["a", "b", "c"]
    archive(source, "channel_1", pd.DataFrame({"value": values}, index=index))
    before = (source / "channels/channel_1.zip").read_bytes()
    with pytest.raises(ValueError, match=message):
        ingest_dataset(source, tmp_path / "store", channels=["channel_1"])
    assert (source / "channels/channel_1.zip").read_bytes() == before
    manifest = json.loads((tmp_path / "store/manifest.json").read_text())
    assert manifest["channels"]["channel_1"]["status"] == "failed"


def test_missing_values_preserved_and_reported(source, tmp_path):
    frame = pd.DataFrame({"value": np.array([1, np.nan, 3], dtype=np.float32)},
                         index=pd.date_range("2001-01-01", periods=3, freq="min"))
    archive(source, "channel_1", frame)
    manifest = ingest_dataset(source, tmp_path / "store", channels=["channel_1"])
    assert manifest["channels"]["channel_1"]["missing_values"] == {"value": 1}
    assert pd.concat(iter_channel_batches(tmp_path / "store", "channel_1")).value.isna().sum() == 1


def test_cadence_estimation_handles_irregular_timestamps():
    origin = pd.Timestamp("2001-01-01", tz="UTC")
    index = pd.DatetimeIndex([origin + pd.Timedelta(seconds=t) for t in [0, 30, 60, 90, 300, 330]])
    result = estimate_cadence(index, max_samples=5)
    assert result["seconds"] == 30
    assert result["sample_max_seconds"] == 210
    assert result["sampled_deltas"] == 5


def test_profile_all_channels_and_annotation_categories(source, tmp_path):
    report = profile_dataset(source, tmp_path / "reports")
    assert report["coverage"] == {"available": 2, "requested": 2, "profiled": 2}
    assert report["status"] == "completed"
    assert report["annotations"]["point_events"] == 1
    assert report["annotations"]["categories"] == {"Rare Event": 1, "Communication Gap": 1}
    assert not list((tmp_path / "reports").glob("*.parquet"))


def test_refuses_artifacts_inside_source_and_path_traversal(source, tmp_path):
    with pytest.raises(ValueError, match="outside"):
        ingest_dataset(source, source / "derived")
    with pytest.raises(ValueError, match="identifier"):
        ingest_dataset(source, tmp_path / "store", channels=["../channel_1"])


def test_missing_or_corrupt_artifact_reingests(source, tmp_path):
    store = tmp_path / "store"
    result = ingest_dataset(source, store, channels=["channel_1"])
    artifact = Path(result["channels"]["channel_1"]["path"])
    artifact.write_bytes(b"damaged")
    result = ingest_dataset(source, store, channels=["channel_1"])
    assert pq.ParquetFile(result["channels"]["channel_1"]["path"]).metadata.num_rows == 23
