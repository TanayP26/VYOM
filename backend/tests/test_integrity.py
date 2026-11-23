"""Integrity verification tests use small real ZIP/pickle and Parquet fixtures."""
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.artifacts import file_sha256
from app.integrity import verify_dataset
from app.storage import ingest_dataset, profile_dataset


@pytest.fixture
def dataset(tmp_path):
    root, store = tmp_path / "source", tmp_path / "store"
    (root / "channels").mkdir(parents=True)
    pd.DataFrame({"Channel": ["channel_1", "channel_2"], "Target": ["YES", "NO"]}).to_csv(root / "channels.csv", index=False)
    for channel in ("channel_1", "channel_2"):
        values = np.arange(31, dtype=np.float32)
        values[2], values[4] = -0., np.nan
        frame = pd.DataFrame({channel: values}, index=pd.date_range("2001", periods=31, freq="30s", tz="UTC"))
        stream = BytesIO()
        frame.to_pickle(stream)
        with ZipFile(root / "channels" / f"{channel}.zip", "w", ZIP_DEFLATED) as archive:
            archive.writestr(f"{channel}.pkl", stream.getvalue())
    ingest_dataset(root, store, row_group_size=7)
    profile_dataset(root, tmp_path / "profile")
    return root, store, tmp_path / "profile/dataset_profile.json"


def mutate_parquet(store, change, update_manifest=True):
    manifest_path = store / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    path = Path(manifest["channels"]["channel_1"]["path"])
    frame = pq.read_table(path).to_pandas()
    frame = change(frame)
    pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), path, row_group_size=7)
    if update_manifest:
        entry = manifest["channels"]["channel_1"]
        entry["file_sha256"] = file_sha256(path)
        entry["file_size_bytes"] = path.stat().st_size
        manifest_path.write_text(json.dumps(manifest))


def test_all_rows_exact_and_resume_without_reloading_source(dataset, tmp_path, monkeypatch):
    root, store, profile = dataset
    result = verify_dataset(root, store, tmp_path / "verification", profile, expected_channels=2, expected_rows=62, batch_size=6)
    assert result["status"] == "verified" and result["verified_rows"] == 62
    assert result["all_rows_compared_exactly"] and result["all_source_archives_sha256_unchanged"]
    channel = result["channels"]["channel_1"]
    assert channel["missing_values"] == {"channel_1": 1}
    assert channel["schema"] == {"channel_1": "float32"}
    assert channel["source_to_parquet_all_timestamps_equal"]
    assert channel["source_sha256_before"] == channel["source_sha256_after"]
    import app.integrity as integrity
    monkeypatch.setattr(integrity, "_load_validated", lambda *_: (_ for _ in ()).throw(AssertionError("completed comparison should resume")))
    resumed = verify_dataset(root, store, tmp_path / "verification", profile, expected_channels=2, expected_rows=62, batch_size=6)
    assert resumed["status"] == "verified" and resumed["resumed_channel_count"] == 2


@pytest.mark.parametrize("kind", ["value", "dtype", "duplicate", "order", "timestamp", "signed_zero", "missing", "row_count", "column", "timestamp_unit"])
def test_corruption_is_detected_even_with_updated_file_hash(dataset, tmp_path, kind):
    root, store, profile = dataset
    def change(frame):
        if kind == "value":
            frame.loc[15, "channel_1"] += .1
        elif kind == "dtype":
            frame["channel_1"] = frame.channel_1.astype("float64")
        elif kind == "duplicate":
            frame.loc[6, "timestamp"] = frame.loc[5, "timestamp"]
        elif kind == "order":
            frame.loc[[6, 7], "timestamp"] = frame.loc[[7, 6], "timestamp"].to_numpy()
        elif kind == "timestamp":
            frame.loc[15, "timestamp"] += pd.Timedelta("1s")
        elif kind == "signed_zero":
            frame.loc[2, "channel_1"] = 0.
        elif kind == "missing":
            frame.loc[4, "channel_1"] = 0.
        elif kind == "row_count":
            return frame.iloc[:-1]
        elif kind == "column":
            return frame.rename(columns={"channel_1": "wrong_channel"})
        elif kind == "timestamp_unit":
            frame["timestamp"] = frame.timestamp.astype("datetime64[us, UTC]")
        return frame
    mutate_parquet(store, change)
    report = verify_dataset(root, store, tmp_path / "verification", profile, batch_size=6)
    assert report["status"] == "failed"
    assert report["channels"]["channel_1"]["status"] == "failed"
    assert report["channels"]["channel_2"]["status"] == "verified"
    assert report["errors"]


def test_manifest_hash_and_profile_row_counts_checked(dataset, tmp_path):
    root, store, profile = dataset
    mutate_parquet(store, lambda frame: frame, update_manifest=False)
    # Equivalent rewritten values can change file representation: force an obvious byte corruption.
    with (store / "channel_1.parquet").open("ab") as stream:
        stream.write(b"changed")
    report = verify_dataset(root, store, tmp_path / "hash_check", profile)
    assert report["status"] == "failed"
    assert "SHA256" in report["channels"]["channel_1"]["error"]
    wrong = json.loads(profile.read_text())
    wrong["channels"]["channel_2"]["rows"] = 30
    profile.write_text(json.dumps(wrong))
    report = verify_dataset(root, store, tmp_path / "profile_check", profile)
    assert "profile rows" in report["channels"]["channel_2"]["error"]


def test_incomplete_and_unexpected_channel_sets_fail_before_scan(dataset, tmp_path):
    root, store, profile = dataset
    (store / "channel_2.parquet").unlink()
    report = verify_dataset(root, store, tmp_path / "verification", profile, expected_channels=2, expected_rows=62)
    assert report["status"] == "failed" and report["verified_channel_count"] == 0
    assert any("channel set" in error for error in report["errors"])
    report = verify_dataset(root, store, tmp_path / "wrong_expectation", profile, expected_channels=76, expected_rows=744856895)
    assert report["status"] == "failed"


def test_resume_rechecks_parquet_bytes_and_source_identity(dataset, tmp_path):
    root, store, profile = dataset
    output = tmp_path / "verification"
    assert verify_dataset(root, store, output, profile)["status"] == "verified"
    mutate_parquet(store, lambda frame: frame.assign(channel_1=frame.channel_1 + 1))
    report = verify_dataset(root, store, output, profile)
    assert report["status"] == "failed" and report["resumed_channel_count"] == 1
    with (root / "channels/channel_2.zip").open("ab") as stream:
        stream.write(b"source changed")
    report = verify_dataset(root, store, tmp_path / "source_changed", profile)
    assert report["status"] == "failed"
    assert any("source identity" in error for error in report["errors"])


def test_interrupted_verification_checkpoints_and_resumes(dataset, tmp_path, monkeypatch):
    root, store, profile = dataset
    import app.integrity as integrity
    actual = integrity._verify_channel
    def interrupted(*args, **kwargs):
        if args[2] == "channel_2":
            raise KeyboardInterrupt("synthetic interruption")
        return actual(*args, **kwargs)
    monkeypatch.setattr(integrity, "_verify_channel", interrupted)
    with pytest.raises(KeyboardInterrupt):
        verify_dataset(root, store, tmp_path / "verification", profile)
    report = json.loads((tmp_path / "verification/integrity_report.json").read_text())
    assert report["status"] == "interrupted"
    assert report["channels"]["channel_1"]["status"] == "verified"
    monkeypatch.setattr(integrity, "_verify_channel", actual)
    result = verify_dataset(root, store, tmp_path / "verification", profile)
    assert result["status"] == "verified" and result["resumed_channel_count"] == 1


def test_output_never_overlaps_original_or_store(dataset):
    root, store, profile = dataset
    for output in (root, root / "derived", store, store / "reports", store.parent):
        with pytest.raises(ValueError, match="outside"):
            verify_dataset(root, store, output, profile)


@pytest.mark.parametrize("damage", ["invalid_json", "missing_path", "invalid_mapping", "missing_manifest", "bad_source_zip"])
def test_invalid_inputs_produce_machine_readable_failures(dataset, tmp_path, damage):
    root, store, profile = dataset
    manifest_path = store / "manifest.json"
    if damage == "invalid_json":
        manifest_path.write_text("not JSON")
    elif damage == "missing_manifest":
        manifest_path.unlink()
    elif damage == "bad_source_zip":
        (root / "channels/channel_1.zip").write_bytes(b"not a ZIP")
    else:
        manifest = json.loads(manifest_path.read_text())
        if damage == "missing_path":
            del manifest["channels"]["channel_1"]["path"]
        else:
            manifest["channels"] = []
        manifest_path.write_text(json.dumps(manifest))
    output = tmp_path / "verification"
    report = verify_dataset(root, store, output, profile)
    assert report["status"] == "failed" and report["errors"]
    assert json.loads((output / "integrity_report.json").read_text())["status"] == "failed"


def test_resource_gate_stops_before_read_and_preserves_recovery(dataset, tmp_path):
    root, store, profile = dataset
    called = []
    def gate(channel):
        called.append(channel)
        if channel == "channel_2":
            raise RuntimeError("insufficient RAM")
    output = tmp_path / "verification"
    with pytest.raises(RuntimeError, match="insufficient RAM"):
        verify_dataset(root, store, output, profile, before_channel=gate)
    assert called == ["channel_1", "channel_2"]
    interrupted = json.loads((output / "integrity_report.json").read_text())
    assert interrupted["status"] == "interrupted"
    assert interrupted["channels"]["channel_1"]["status"] == "verified"
    assert interrupted["channels"]["channel_2"]["stage"] == "before_channel"
    resumed = verify_dataset(root, store, output, profile)
    assert resumed["status"] == "verified" and resumed["resumed_channel_count"] == 1


@pytest.mark.parametrize("corrupt", [False, True])
def test_parquet_reader_closes_after_success_or_validation_failure(dataset, tmp_path, monkeypatch, corrupt):
    root, store, profile = dataset
    if corrupt:
        mutate_parquet(store, lambda frame: frame.assign(channel_1=frame.channel_1 + 1))
    original = pq.ParquetFile
    opened, closed = [], []
    def tracked(path, *args, **kwargs):
        reader = original(path, *args, **kwargs)
        opened.append(path)
        close = reader.close
        def recorded_close():
            closed.append(path)
            close()
        reader.close = recorded_close
        return reader
    monkeypatch.setattr(pq, "ParquetFile", tracked)
    report = verify_dataset(root, store, tmp_path / "verification", profile)
    assert report["status"] == ("failed" if corrupt else "verified")
    assert opened == closed and len(closed) == 2
