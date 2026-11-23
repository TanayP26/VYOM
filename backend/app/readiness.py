"""M1.2 freeze, resource gates and sequential ingestion; never runs a detector."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil

import psutil

from app.artifacts import ResourceMonitor, configure_logging, file_sha256, utc_now
from app.storage import atomic_json, dataset_identity, ingest_dataset

GIB = 1024 ** 3
MIB = 1024 ** 2
EXPECTED_ROWS = 744_856_895
EXPECTED_CHANNELS = 76


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def file_inventory(root, paths):
    return {str(p.relative_to(root)).replace("\\", "/"): {
        "bytes": p.stat().st_size, "sha256": file_sha256(p)} for p in sorted(paths)}


def freeze(repo, output, source):
    """Create once; retries cannot replace the original preservation baseline."""
    target = output / "freeze.json"
    if target.exists():
        return read_json(target)
    output.mkdir(parents=True, exist_ok=True)
    old_artifacts = [p for p in (repo / "artifacts").rglob("*")
                     if p.is_file() and output not in p.parents]
    comparison = read_json(repo / "artifacts/milestone11/comparison_final/manifest.json")
    code = [repo / "backend/app" / name for name in comparison["code_sha256"]]
    for path in code:
        if file_sha256(path) != comparison["code_sha256"][path.name]:
            raise RuntimeError(f"Pre-freeze engine differs from M1.1: {path.name}")
    configs = [p for p in old_artifacts if p.name in {
        "manifest.json", "model_configuration.json", "threshold_calibration.json", "features.json"}]
    for path in [*code, *configs, repo / "backend/requirements.txt"]:
        destination = output / "frozen" / path.relative_to(repo)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
    protected = [p for p in (repo / "frontend").rglob("*") if p.is_file()
                 and not {"node_modules", "dist", ".next"}.intersection(p.parts)]
    protected += [p for p in (repo / "docs").glob("*.md") if not p.name.startswith("M12")]
    protected += [p for p in code if p.name != "storage.py"]
    protected += [p for p in (repo / "backend").glob(".env*") if p.is_file()]
    result = {
        "created_at": utc_now(), "source_root": str(source),
        "policy": "No model fitting, parameter changes or benchmark execution in M1.2",
        "existing_artifacts": file_inventory(repo, old_artifacts),
        "source_files": file_inventory(source, (p for p in source.rglob("*") if p.is_file())),
        "protected_files": file_inventory(repo, protected),
        "configuration_files": file_inventory(repo, configs),
        "frozen_code": comparison["code_sha256"],
        "comparison_configuration": comparison["configuration"],
        "environment": {"python": platform.python_version(), "packages": {
            name: importlib.metadata.version(name) for name in
            ("numpy", "pandas", "pyarrow", "scikit-learn", "psutil")}},
        "frozen_copies": file_inventory(output / "frozen", (p for p in (output / "frozen").rglob("*") if p.is_file())),
    }
    atomic_json(target, result)
    return result


def estimate_resources(profile, pilot, pilot_resources):
    rows = sum(c["rows"] for c in profile["channels"].values())
    pilot_rows = sum(c["rows"] for c in pilot["channels"].values())
    pilot_bytes = sum(c["file_size_bytes"] for c in pilot["channels"].values())
    largest_frame = max(c["dataframe_bytes"] for c in profile["channels"].values())
    peak = pilot_resources["peak_sampled_rss_mib"] * MIB
    linear_seconds = pilot_resources["wall_seconds"] * rows / pilot_rows
    # Estimates are engineering allowances, not a statistical confidence interval.
    process_budget = max(1.5 * peak, 3 * largest_frame + 128 * MIB)
    return {
        "rows": rows, "channels": len(profile["channels"]),
        "pilot_rows": pilot_rows, "pilot_bytes": pilot_bytes,
        "pilot_bytes_per_row": pilot_bytes / pilot_rows,
        "pilot_channel_bytes_per_row_range": [
            f(c["file_size_bytes"] / c["rows"] for c in pilot["channels"].values())
            for f in (min, max)],
        "parquet_central_bytes": int(rows * pilot_bytes / pilot_rows),
        "parquet_upper_allowance_bytes": rows * 16,
        "temporary_allowance_bytes": GIB,
        "free_disk_reserve_bytes": 10 * GIB,
        "required_free_disk_bytes": rows * 16 + 11 * GIB,
        "process_peak_budget_bytes": int(process_budget),
        "ram_reserve_bytes": 512 * MIB,
        "required_available_ram_bytes": int(process_budget + 512 * MIB),
        "pilot_peak_rss_mib": pilot_resources["peak_sampled_rss_mib"],
        "largest_source_dataframe_bytes": largest_frame,
        "ingestion_linear_reference_seconds": linear_seconds,
        "ingestion_planning_range_seconds": [linear_seconds * 2, linear_seconds * 6],
        "integrity_planning_range_seconds": [120, 600],
        "uncertainty": ["Five pilot channels are not a random compression sample",
                        "Cache, antivirus, disk contention, paging and thermal throttling",
                        "Pickle decode materializes one channel; no dataset-wide frame",
                        "Integrity includes a second decode plus full Parquet reads and hashes"],
    }


def resource_gate(output, estimates, remaining_rows=None):
    free = shutil.disk_usage(output).free
    memory = psutil.virtual_memory()
    required_disk = (estimates["required_free_disk_bytes"] if remaining_rows is None else
                     remaining_rows * 16 + estimates["temporary_allowance_bytes"] +
                     estimates["free_disk_reserve_bytes"])
    result = {"at": utc_now(), "free_disk_bytes": free,
              "total_ram_bytes": memory.total, "available_ram_bytes": memory.available,
              "required_disk_bytes": required_disk,
              "required_available_ram_bytes": estimates["required_available_ram_bytes"]}
    result["safe"] = free >= required_disk and memory.available >= result["required_available_ram_bytes"]
    return result


def preflight(repo, output, source):
    frozen = freeze(repo, output, source)
    profile = read_json(repo / "artifacts/profile/dataset_profile.json")
    identity = dataset_identity(source)
    if identity != profile["dataset"]:
        raise RuntimeError("Current source identity differs from preserved profile")
    estimate = estimate_resources(profile, read_json(repo / "artifacts/telemetry/manifest.json"),
                                  read_json(repo / "artifacts/telemetry/ingest_resources.json"))
    if estimate["rows"] != EXPECTED_ROWS or estimate["channels"] != EXPECTED_CHANNELS:
        raise RuntimeError("Full profile does not match requested 76-channel dataset")
    report = {"created_at": utc_now(), "freeze_created_at": frozen["created_at"],
              "estimates": estimate, "live_gate": resource_gate(output, estimate),
              "source_fingerprint": identity["fingerprint"],
              "profile_sha256": file_sha256(repo / "artifacts/profile/dataset_profile.json"),
              "count_provenance": "Prior complete source scan; channels.csv has no row counts"}
    atomic_json(output / "preflight.json", report)
    history_path = output / "preflight_history.json"
    history = read_json(history_path) if history_path.exists() else []
    atomic_json(history_path, [*history, report])
    return report


def check_preservation(repo, output, source):
    frozen = read_json(output / "freeze.json")
    failures = []
    counts = {}
    for category, root in (("existing_artifacts", repo), ("source_files", source),
                           ("protected_files", repo), ("frozen_copies", output / "frozen")):
        entries = frozen[category]
        for name, expected in entries.items():
            path = root / name
            if not path.is_file() or path.stat().st_size != expected["bytes"] or file_sha256(path) != expected["sha256"]:
                failures.append(f"{category}:{name}")
        counts[category] = len(entries)
    original_source_names = set(frozen["source_files"])
    current_source_names = {p.relative_to(source).as_posix() for p in source.rglob("*") if p.is_file()}
    if current_source_names != original_source_names:
        failures.append("source file inventory changed")
    report = {"checked_at": utc_now(), "status": "verified" if not failures else "failed",
              "checked_file_counts": counts, "failures": failures}
    atomic_json(output / "preservation_report.json", report)
    if failures:
        raise RuntimeError(f"Preservation failed: {failures}")
    return report


def ingest_full(repo, output, source):
    from app.artifacts import run_lock
    with run_lock(output / "orchestration"):
        pre = read_json(output / "preflight.json")
        profile = read_json(repo / "artifacts/profile/dataset_profile.json")
        if file_sha256(repo / "artifacts/profile/dataset_profile.json") != pre["profile_sha256"]:
            raise RuntimeError("Profile changed since preflight")
        if dataset_identity(source)["fingerprint"] != pre["source_fingerprint"]:
            raise RuntimeError("Dataset changed since preflight")
        channels = list(profile["channels"])
        execution = {"started_at": utc_now(), "status": "running", "channel_gates": []}
        before = shutil.disk_usage(output).free
        try:
            with ResourceMonitor() as monitor:
                for position, channel in enumerate(channels):
                    remaining = sum(profile["channels"][name]["rows"] for name in channels[position:])
                    gate = resource_gate(output, pre["estimates"], remaining)
                    execution["channel_gates"].append({"channel": channel, **gate})
                    atomic_json(output / "ingestion_execution.json", execution)
                    if not gate["safe"]:
                        raise RuntimeError(f"Resource gate paused before {channel}; close unrelated workloads and resume")
                    ingest_dataset(source, output / "telemetry", channels=[channel])
                # Set complete selected-channel coverage while hash-checking every output on resume.
                manifest = ingest_dataset(source, output / "telemetry")
                if sum(c["rows"] for c in manifest["channels"].values()) != EXPECTED_ROWS:
                    raise RuntimeError("Ingested total differs from preflight")
            execution["status"] = "completed"
        except BaseException as exc:
            execution.update(status="interrupted", error=f"{type(exc).__name__}: {exc}")
            raise
        finally:
            execution.update(finished_at=utc_now(), resources=monitor.measurements,
                             free_disk_before_bytes=before, free_disk_after_bytes=shutil.disk_usage(output).free)
            atomic_json(output / "ingestion_execution.json", execution)
            history = output / "ingestion_history.json"
            entries = read_json(history) if history.exists() else []
            atomic_json(history, [*entries, execution])
        return execution


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["preflight", "ingest", "verify", "preservation"])
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    repo = args.repo.resolve()
    output = repo / "artifacts/milestone12"
    source = repo / "data/esa_adb/mission1/ESA-Mission1"
    configure_logging()
    if args.phase == "preflight":
        result = preflight(repo, output, source)
    elif args.phase == "ingest":
        result = ingest_full(repo, output, source)
    elif args.phase == "preservation":
        result = check_preservation(repo, output, source)
    else:
        from app.integrity import verify_dataset
        gate = resource_gate(output, read_json(output / "preflight.json")["estimates"], 0)
        if not gate["safe"]:
            raise RuntimeError("Resource gate paused before integrity verification")
        def before_channel(channel):
            live = resource_gate(output, read_json(output / "preflight.json")["estimates"], 0)
            if not live["safe"]:
                raise RuntimeError(f"Resource gate paused integrity before {channel}")
        result = verify_dataset(source, output / "telemetry", output / "integrity",
                                profile_path=repo / "artifacts/profile/dataset_profile.json",
                                expected_channels=EXPECTED_CHANNELS, expected_rows=EXPECTED_ROWS,
                                before_channel=before_channel)
        if result["status"] != "verified":
            raise RuntimeError("Integrity verification did not pass")
    print(json.dumps({k: v for k, v in result.items() if k not in {"channels", "channel_gates"}}, default=str))


if __name__ == "__main__":
    main()
