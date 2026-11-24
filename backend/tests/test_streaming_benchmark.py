"""Bounded runner parity, label isolation, explicit failures and exact recovery."""
import json

import numpy as np
import pandas as pd
import pytest

from app.artifacts import file_sha256
from app.streaming_benchmark import ParquetChannel, run_channel
from app.streaming_checkpoint import FragmentJournal


@pytest.fixture
def stream_case(tmp_path):
    rows = 420
    deltas = np.r_[np.full(300, 60), np.full(rows - 301, 90)]
    index = pd.DatetimeIndex(pd.Timestamp("2000", tz="UTC") +
                             pd.to_timedelta(np.r_[0, np.cumsum(deltas)], unit="s"))
    values = (1 + .02*np.sin(np.arange(rows)/9)).astype(np.float32)
    values[350:365] += .6
    frame = pd.DataFrame({"channel_x": values}, index=index)
    frame.index.name = "timestamp"
    path = tmp_path / "channel_x.parquet"
    frame.to_parquet(path, row_group_size=53)
    annotations = pd.DataFrame({"ID": ["point", "interval", "gap"],
        "StartTime": [index[345], index[350], index[390]+pd.Timedelta(1, "ns")],
        "EndTime": [index[345], index[364], index[391]-pd.Timedelta(1, "ns")],
        "Category": ["Anomaly", "Rare Event", "Communication Gap"]})
    return path, frame, annotations


def _journal(output):
    config = json.loads((output/"run_configuration.json").read_text())
    journal = FragmentJournal(output/"journal", config["identities"])
    journal.load()
    return journal


def _predictions(output):
    return pd.concat(frame for _, frame in _journal(output).frames("predictions"))


def _events(output):
    result = []
    for _, path, _ in _journal(output).fragments("events"):
        result.extend(json.loads(line) for line in path.read_text().splitlines())
    return result


def test_parquet_reader_seeks_by_ordinal_without_materializing_channel(stream_case):
    path, frame, _ = stream_case
    source = ParquetChannel(path, base_row=11, rows=111, batch_size=13,
                            expected_sha256=file_sha256(path))
    actual = pd.concat(list(source.batches(17, 93)))
    expected = frame.iloc[28:104, 0].copy()
    expected.index = expected.index.as_unit("ns")
    pd.testing.assert_series_equal(actual, expected, check_freq=False)
    split = source.split()
    assert split["train_rows"] == 66 and split["validation_rows"] == 22 and split["test_rows"] == 23
    assert source.rows_read < len(frame) and source.read_seconds > 0


def test_runner_is_batch_invariant_and_reads_labels_only_after_scoring(stream_case, tmp_path):
    path, _, annotations = stream_case
    calls = []

    def labels():
        calls.append("labels")
        return annotations.copy()

    reports = []
    for size in (37, 71):
        reports.append(run_channel(path, tmp_path/f"run_{size}", "channel_x", labels,
            batch_size=size, scope="synthetic", expected_sha256=file_sha256(path)))
    assert calls == ["labels", "labels"]
    pd.testing.assert_frame_equal(_predictions(tmp_path/"run_37"),
                                  _predictions(tmp_path/"run_71"), check_freq=False, check_exact=True)
    assert _events(tmp_path/"run_37") == _events(tmp_path/"run_71")
    for report in reports:
        assert report["split"]["train_fraction"] == .6
        assert report["frozen"]["labels_used_for_training_or_calibration"] is False
        assert report["communication_gaps"]["sample"] is None
        assert report["random_forest"]["status"] == "unsupported"


def test_runner_resumes_after_committed_interruption_without_duplicates(stream_case, tmp_path):
    path, _, annotations = stream_case
    output = tmp_path/"interrupted"
    committed = 0

    def fault(stage):
        nonlocal committed
        if stage == "after_pointer":
            committed += 1
            if committed == 8:
                raise KeyboardInterrupt("simulated process interruption")

    with pytest.raises(KeyboardInterrupt):
        run_channel(path, output, "channel_x", lambda: annotations, batch_size=47,
                    scope="synthetic", expected_sha256=file_sha256(path), fault=fault)
    assert (output/"last_failure.json").is_file()
    recovered = run_channel(path, output, "channel_x", lambda: annotations, batch_size=47,
                            scope="synthetic", expected_sha256=file_sha256(path))
    clean_output = tmp_path/"clean"
    clean = run_channel(path, clean_output, "channel_x", lambda: annotations, batch_size=47,
                        scope="synthetic", expected_sha256=file_sha256(path))
    pd.testing.assert_frame_equal(_predictions(output), _predictions(clean_output), check_exact=True)
    assert _events(output) == _events(clean_output)
    assert recovered["models"] == clean["models"]


def test_hash_change_and_unreviewed_B_split_fail_before_fit(stream_case, tmp_path):
    path, _, annotations = stream_case
    with pytest.raises(ValueError, match="source hash changed"):
        run_channel(path, tmp_path/"bad_hash", "channel_x", lambda: annotations,
                    expected_sha256="0"*64, scope="synthetic")
    with pytest.raises(ValueError, match="frozen 60/20/20"):
        run_channel(path, tmp_path/"bad_split", "channel_x", lambda: annotations,
                    expected_sha256=file_sha256(path), scope="B", train_fraction=.5)
