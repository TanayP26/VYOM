"""Small end-to-end experiments validate artifact and leakage contracts."""
from dataclasses import replace
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from app.artifacts import file_sha256
from app.experiment import ExperimentConfig, run_experiment
from app.features import FeatureConfig
from app.storage import ingest_dataset


def write_source(root, *, altered_test=False, target="YES"):
    (root / "channels").mkdir(parents=True, exist_ok=True)
    index = pd.date_range("2001-01-01", periods=240, freq="30s", tz="UTC")
    index = index[:207].append(index[207:] + pd.Timedelta("30min"))
    values = np.random.default_rng(23).normal(10, .2, len(index)).astype(np.float32)
    values[180] = 25
    values[190:194] = [20, 23, 20, 23]
    if altered_test:
        values[168:] += np.arange(72, dtype=np.float32) * 1000
    frame = pd.DataFrame({"value": values}, index=index)
    buffer = BytesIO()
    frame.to_pickle(buffer)
    with ZipFile(root / "channels/channel_1.zip", "w", ZIP_DEFLATED) as archive:
        archive.writestr("channel_1.pkl", buffer.getvalue())
    pd.DataFrame({"Channel": ["channel_1"], "Subsystem": ["subsystem_1"],
        "Physical Unit": ["physical_unit_1"], "Group": [1], "Target": [target]}).to_csv(root / "channels.csv", index=False)
    pd.DataFrame({"ID": ["point", "interval", "gap"], "Channel": ["channel_1"] * 3,
        "StartTime": [index[180], index[190], index[206] + pd.Timedelta("30s")],
        "EndTime": [index[180], index[193], index[207] - pd.Timedelta("30s")]}).to_csv(root / "labels.csv", index=False)
    pd.DataFrame({"ID": ["point", "interval", "gap"], "Category": ["Anomaly", "Rare Event", "Communication Gap"],
        "Class": ["test"] * 3, "Subclass": ["test"] * 3}).to_csv(root / "anomaly_types.csv", index=False)
    pd.DataFrame({"Telecommand": [], "Priority": []}).to_csv(root / "telecommands.csv", index=False)
    return frame


@pytest.fixture
def experiment_source(tmp_path):
    root, store = tmp_path / "source", tmp_path / "store"
    frame = write_source(root)
    ingest_dataset(root, store, row_group_size=41)
    return root, store, frame


@pytest.fixture
def configuration():
    return ExperimentConfig(batch_size=31, max_train_rows=100, n_estimators=8, seed=17,
        statistical_quantile=.99, unlabelled_policy="assume_normal",
        features=FeatureConfig(window_samples=12, scales=(1, 2), block_size=32))


def report(manifest):
    return json.loads(Path(manifest["channels"]["channel_1"]["report"]).read_text())


def test_end_to_end_metrics_and_resume(experiment_source, configuration, tmp_path):
    root, store, frame = experiment_source
    output = tmp_path / "run"
    manifest = run_experiment(root, store, output, config=configuration)
    result = report(manifest)
    assert manifest["status"] == "completed"
    assert result["selection"]["train_rows"] == 168
    assert result["selection"]["test_rows"] == 72
    assert pd.Timestamp(result["selection"]["train_end"]) == frame.index[167]
    assert pd.Timestamp(result["selection"]["test_start"]) == frame.index[168]
    assert result["models"]["value"]["training_sample_rows"] == 100
    assert result["metrics"]["sample"]["statistical"]["tp"] >= 1
    assert result["metrics"]["sample"]["combined"]["evaluated_samples"] == 72
    assert set(result["metrics"]["per_category"]) == {"Anomaly", "Rare Event", "Communication Gap"}
    assert result["metrics"]["communication_gap"]["event"]["tp"] == 1
    assert pq.ParquetFile(result["artifacts"]["predictions"]).metadata.num_rows == 72
    hashes = manifest["channels"]["channel_1"]["artifacts_sha256"]
    assert {"features_0.parquet", "isolation_forest_0.joblib", "report.json"}.issubset(hashes)
    mtime = (output / "channel_1/report.json").stat().st_mtime_ns
    resumed = run_experiment(root, store, output, config=configuration)
    assert (output / "channel_1/report.json").stat().st_mtime_ns == mtime
    assert report(resumed)["metrics"] == result["metrics"]
    assert len(resumed["executions"]) == 2
    assert resumed["executions"][0]["peak_sampled_rss_mib"] > 0


@pytest.mark.parametrize("artifact", ["features_0.parquet", "isolation_forest_0.joblib", "events.jsonl", "report.json"])
def test_corrupted_nested_artifacts_restart_channel(experiment_source, configuration, tmp_path, artifact):
    root, store, _ = experiment_source
    output = tmp_path / "run"
    first = run_experiment(root, store, output, config=configuration)
    original_metrics = report(first)["metrics"]
    path = output / "channel_1" / artifact
    path.write_bytes(b"damaged artifact")
    second = run_experiment(root, store, output, config=configuration)
    assert second["status"] == "completed"
    assert path.read_bytes() != b"damaged artifact"
    assert second["channels"]["channel_1"]["completed_at"] != first["channels"]["channel_1"]["completed_at"]
    assert original_metrics == report(second)["metrics"]


def test_resume_rejects_configuration_changes(experiment_source, configuration, tmp_path):
    root, store, _ = experiment_source
    output = tmp_path / "run"
    run_experiment(root, store, output, config=configuration)
    with pytest.raises(ValueError, match="configuration, dataset or code changed"):
        run_experiment(root, store, output, config=replace(configuration, seed=999))


@pytest.mark.parametrize("changed", ["source", "metadata", "parquet"])
def test_analysis_rejects_stale_or_corrupt_ingestion(experiment_source, configuration, tmp_path, changed):
    root, store, _ = experiment_source
    if changed == "source":
        write_source(root, altered_test=True)
    elif changed == "metadata":
        with (root / "labels.csv").open("a") as stream:
            stream.write("\n")
    else:
        (store / "channel_1.parquet").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="changed since ingestion|integrity check failed"):
        run_experiment(root, store, tmp_path / "run", config=configuration)


def test_changed_test_tail_cannot_change_training_features_or_thresholds(experiment_source, configuration, tmp_path):
    root, store, _ = experiment_source
    first = report(run_experiment(root, store, tmp_path / "first", config=configuration))
    changed_source, changed_store = tmp_path / "changed_source", tmp_path / "changed_store"
    write_source(changed_source, altered_test=True)
    ingest_dataset(changed_source, changed_store, row_group_size=41)
    second = report(run_experiment(changed_source, changed_store, tmp_path / "second", config=configuration))
    assert first["models"]["value"]["statistical"]["threshold"] == second["models"]["value"]["statistical"]["threshold"]
    assert first["models"]["value"]["isolation_forest"]["threshold"] == second["models"]["value"]["isolation_forest"]["threshold"]
    first_features = pq.read_table(tmp_path / "first/channel_1/features_0.parquet").to_pandas().iloc[:168]
    second_features = pq.read_table(tmp_path / "second/channel_1/features_0.parquet").to_pandas().iloc[:168]
    pd.testing.assert_frame_equal(first_features, second_features)
    assert file_sha256(first["models"]["value"]["artifact"]) == file_sha256(second["models"]["value"]["artifact"])


def test_output_must_not_overlap_sources_or_store(experiment_source, configuration):
    root, store, _ = experiment_source
    for output in (root, root / "run", store, store / "run", store.parent):
        with pytest.raises(ValueError, match="outside the original dataset"):
            run_experiment(root, store, output, config=configuration)


def test_empty_channel_selection_is_not_full_dataset(experiment_source, configuration, tmp_path):
    root, store, _ = experiment_source
    with pytest.raises(ValueError, match="nonempty"):
        run_experiment(root, store, tmp_path / "run", channels=[], config=configuration)


def test_interrupted_channel_is_restarted(experiment_source, configuration, tmp_path, monkeypatch):
    import app.experiment as experiment
    root, store, _ = experiment_source
    output = tmp_path / "run"
    original = experiment._channel_analysis
    def interrupt(*args, **kwargs):
        original(*args, **kwargs)
        raise KeyboardInterrupt("interrupted after channel artifact creation")
    monkeypatch.setattr(experiment, "_channel_analysis", interrupt)
    with pytest.raises(KeyboardInterrupt):
        run_experiment(root, store, output, config=configuration)
    failed = json.loads((output / "manifest.json").read_text())
    assert failed["status"] == "interrupted"
    assert failed["channels"]["channel_1"]["status"] == "interrupted"
    monkeypatch.setattr(experiment, "_channel_analysis", original)
    resumed = run_experiment(root, store, output, config=configuration)
    assert resumed["status"] == "completed"
    assert "error" not in resumed
    assert report(resumed)["selection"]["test_rows"] == 72
