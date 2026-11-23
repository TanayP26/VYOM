"""Meaningful resource estimation/gating and preservation failure checks."""
from types import SimpleNamespace

import pytest

from app import readiness
from app.storage import atomic_json


def test_estimate_uses_non_linear_allowances_and_source_memory_floor():
    profile = {"channels": {"a": {"rows": 1000, "dataframe_bytes": 500_000_000}}}
    pilot = {"channels": {"a": {"rows": 100, "file_size_bytes": 700}}}
    estimates = readiness.estimate_resources(profile, pilot,
        {"wall_seconds": 3, "peak_sampled_rss_mib": 400})
    assert estimates["parquet_central_bytes"] == 7000
    assert estimates["parquet_upper_allowance_bytes"] == 16000
    assert estimates["ingestion_linear_reference_seconds"] == 30
    assert estimates["ingestion_planning_range_seconds"] == [60, 180]
    assert estimates["process_peak_budget_bytes"] >= 3 * 500_000_000
    assert estimates["required_free_disk_bytes"] > estimates["parquet_upper_allowance_bytes"]


@pytest.mark.parametrize("disk,ram,safe", [(1000, 500, True), (999, 500, False), (1000, 499, False)])
def test_live_gate_requires_both_resources(monkeypatch, tmp_path, disk, ram, safe):
    monkeypatch.setattr(readiness.shutil, "disk_usage", lambda _: SimpleNamespace(free=disk))
    monkeypatch.setattr(readiness.psutil, "virtual_memory", lambda: SimpleNamespace(total=16000, available=ram))
    gate = readiness.resource_gate(tmp_path, {"required_free_disk_bytes": 1000,
                                             "required_available_ram_bytes": 500})
    assert gate["safe"] is safe


def test_preservation_detects_same_size_byte_change(tmp_path):
    repo, source, output = tmp_path / "repo", tmp_path / "source", tmp_path / "output"
    repo.mkdir(); source.mkdir(); output.mkdir()
    artifact = repo / "result.json"
    artifact.write_bytes(b"old")
    atomic_json(output / "freeze.json", {"existing_artifacts": readiness.file_inventory(repo, [artifact]),
        "source_files": {}, "protected_files": {}, "frozen_copies": {}})
    assert readiness.check_preservation(repo, output, source)["status"] == "verified"
    artifact.write_bytes(b"new")
    with pytest.raises(RuntimeError, match="Preservation failed"):
        readiness.check_preservation(repo, output, source)
    assert readiness.read_json(output / "preservation_report.json")["status"] == "failed"
