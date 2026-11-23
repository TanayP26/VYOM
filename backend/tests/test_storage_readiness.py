"""Failure and recovery contracts needed before full-dataset ingestion."""
from io import BytesIO
import hashlib
import json
import os
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np
import pandas as pd
import pytest

from app import storage


def test_keyboard_interrupt_is_checkpointed_and_retry_is_exact(small_source, tmp_path, monkeypatch):
    root, expected = small_source
    store = tmp_path / "interrupt_store"
    original = storage._arrow_table
    calls = 0

    def interrupt(frame):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise KeyboardInterrupt("simulated cancellation")
        return original(frame)

    monkeypatch.setattr(storage, "_arrow_table", interrupt)
    with pytest.raises(KeyboardInterrupt):
        storage.ingest_dataset(root, store, row_group_size=7)
    assert read_manifest(store)["status"] == "interrupted"
    assert read_manifest(store)["channels"]["channel_1"]["status"] == "interrupted"
    monkeypatch.setattr(storage, "_arrow_table", original)
    storage.ingest_dataset(root, store, row_group_size=7)
    assert_full_round_trip(store, expected)


def test_reader_closes_when_consumer_stops_early(small_source, tmp_path, monkeypatch):
    root, _ = small_source
    store = tmp_path / "closed_store"
    storage.ingest_dataset(root, store, row_group_size=7)
    original = storage.pq.ParquetFile
    readers = []

    def track(*args, **kwargs):
        reader = original(*args, **kwargs)
        readers.append(reader)
        return reader

    monkeypatch.setattr(storage.pq, "ParquetFile", track)
    iterator = storage.iter_channel_batches(store, "channel_1", batch_size=3)
    next(iterator)
    assert not readers[-1].closed
    iterator.close()
    assert readers[-1].closed


@pytest.fixture
def small_source(tmp_path):
    root = tmp_path / "source"
    (root / "channels").mkdir(parents=True)
    pd.DataFrame({"Channel": ["channel_1"], "Target": ["NO"]}).to_csv(
        root / "channels.csv", index=False)
    frame = pd.DataFrame({"value": np.arange(29, dtype=np.float32)},
                         index=pd.date_range("2001-01-01", periods=29, freq="30s"))
    payload = BytesIO()
    frame.to_pickle(payload)
    with ZipFile(root / "channels/channel_1.zip", "w", ZIP_DEFLATED) as archive:
        archive.writestr("channel_1.pkl", payload.getvalue())
    return root, frame


def read_manifest(store):
    return json.loads((store / "manifest.json").read_text(encoding="utf-8"))


def assert_full_round_trip(store, expected):
    actual = pd.concat(storage.iter_channel_batches(store, "channel_1", batch_size=3))
    expected = expected.copy()
    expected.index = expected.index.tz_localize("UTC").as_unit("ns").rename("timestamp")
    pd.testing.assert_frame_equal(actual, expected, check_freq=False)
    assert actual.index.is_unique


def test_partial_write_retry_restarts_channel_without_duplicate_rows(small_source, tmp_path, monkeypatch):
    root, expected = small_source
    store = tmp_path / "store"
    original = storage._arrow_table
    calls = 0

    def interrupted_conversion(frame):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("simulated write interruption")
        return original(frame)

    monkeypatch.setattr(storage, "_arrow_table", interrupted_conversion)
    with pytest.raises(OSError, match="simulated write interruption"):
        storage.ingest_dataset(root, store, row_group_size=7)
    manifest = read_manifest(store)
    assert manifest["status"] == "failed"
    assert manifest["channels"]["channel_1"]["status"] == "failed"
    assert (store / ".channel_1.parquet.partial").is_file()
    assert not (store / "channel_1.parquet").exists()

    monkeypatch.setattr(storage, "_arrow_table", original)
    storage.ingest_dataset(root, store, row_group_size=7)
    assert_full_round_trip(store, expected)
    assert not (store / ".channel_1.parquet.partial").exists()


def test_failed_forced_rebuild_keeps_previous_committed_file(small_source, tmp_path, monkeypatch):
    root, expected = small_source
    store = tmp_path / "store"
    storage.ingest_dataset(root, store, row_group_size=7)
    artifact = store / "channel_1.parquet"
    committed = artifact.read_bytes()
    original = storage._load_validated

    def fail_read(*args):
        raise OSError("simulated source read failure")

    monkeypatch.setattr(storage, "_load_validated", fail_read)
    with pytest.raises(OSError, match="source read failure"):
        storage.ingest_dataset(root, store, force=True, row_group_size=7)
    assert artifact.read_bytes() == committed
    assert read_manifest(store)["channels"]["channel_1"]["status"] == "failed"

    monkeypatch.setattr(storage, "_load_validated", original)
    storage.ingest_dataset(root, store, row_group_size=7)
    assert_full_round_trip(store, expected)


def test_same_size_artifact_tampering_is_not_skipped(small_source, tmp_path):
    root, expected = small_source
    store = tmp_path / "store"
    first = storage.ingest_dataset(root, store, row_group_size=7)
    artifact = store / "channel_1.parquet"
    damaged = bytearray(artifact.read_bytes())
    damaged[4] ^= 1  # Preserve file size and footer metadata but change the data bytes.
    artifact.write_bytes(damaged)
    assert artifact.stat().st_size == first["channels"]["channel_1"]["file_size_bytes"]

    resumed = storage.ingest_dataset(root, store, row_group_size=7)
    assert resumed["channels"]["channel_1"]["file_sha256"] == hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert resumed["channels"]["channel_1"]["completed_at"] != first["channels"]["channel_1"]["completed_at"]
    assert_full_round_trip(store, expected)


def test_source_change_during_decode_prevents_commit(small_source, tmp_path, monkeypatch):
    root, _ = small_source
    store = tmp_path / "store"
    original = storage._load_validated

    def changed_source(*args):
        result = original(*args)
        archive = root / "channels/channel_1.zip"
        stat = archive.stat()
        os.utime(archive, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
        return result

    monkeypatch.setattr(storage, "_load_validated", changed_source)
    with pytest.raises(RuntimeError, match="source changed during ingestion"):
        storage.ingest_dataset(root, store, row_group_size=7)
    assert not (store / "channel_1.parquet").exists()
    assert read_manifest(store)["status"] == "failed"


def test_active_writer_is_rejected_and_stale_lock_file_is_reusable(small_source, tmp_path):
    root, expected = small_source
    store = tmp_path / "store"
    store.mkdir()
    with storage._store_lock(store):
        with pytest.raises(RuntimeError, match="Another ingestion owns"):
            storage.ingest_dataset(root, store, row_group_size=7)
        assert not (store / "manifest.json").exists()
    assert (store / ".ingestion.lock").exists()
    storage.ingest_dataset(root, store, row_group_size=7)
    assert_full_round_trip(store, expected)
