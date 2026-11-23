"""Offline profiling, ingestion and reproducible benchmark commands."""
import argparse
import json
from pathlib import Path
import sys

from app.artifacts import atomic_json, configure_logging, ResourceMonitor
from app.core import settings
from app.experiment import ExperimentConfig, run_experiment
from app.features import FeatureConfig
from app.storage import ingest_dataset, profile_dataset
from app.telemetry import resolve_dataset


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    for name in ("profile", "ingest", "evaluate"):
        command = commands.add_parser(name)
        command.add_argument("--dataset", help="Read-only ESA-Mission1 directory; defaults to DATASET_DIR")
        command.add_argument("--channels", nargs="+", help="Channel names or numbers; omit for all catalog channels")
        command.add_argument("--output", required=True, type=Path)
        if name == "ingest":
            command.add_argument("--force", action="store_true")
            command.add_argument("--row-group-size", type=int, default=250000)
        if name == "evaluate":
            command.add_argument("--store", required=True, type=Path)
            command.add_argument("--max-rows", type=int, help="Pilot prefix bound per channel; omit for full period")
            command.add_argument("--batch-size", type=int, default=25000)
            command.add_argument("--max-train-rows", type=int, default=20000)
            command.add_argument("--train-fraction", type=float, default=.7)
            command.add_argument("--seed", type=int, default=42)
            command.add_argument("--contamination", type=float, default=.01)
            command.add_argument("--n-estimators", type=int, default=100)
            command.add_argument("--threshold", type=float, default=6.0)
            command.add_argument("--threshold-quantile", type=float)
            command.add_argument("--gap-factor", type=float, default=3.0)
            command.add_argument("--point-tolerance-cadences", type=float, default=.5)
            command.add_argument("--unlabelled-policy", choices=("exclude", "assume_normal"), default="exclude")
            command.add_argument("--window-samples", type=int, default=30)
            command.add_argument("--scales", nargs="+", type=int, default=[1, 4])
            command.add_argument("--max-history-rows", type=int, default=10000)
            command.add_argument("--start", help="Inclusive UTC selection start")
            command.add_argument("--end", help="Inclusive UTC selection end")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    configure_logging()
    root = resolve_dataset(args.dataset or settings().dataset_dir)
    channels = [f"channel_{int(c)}" if c.isdecimal() else c for c in args.channels] if args.channels else None
    with ResourceMonitor() as monitor:
        if args.command == "profile":
            result = profile_dataset(root, args.output, channels=channels)
        elif args.command == "ingest":
            result = ingest_dataset(root, args.output, channels=channels, force=args.force,
                                    row_group_size=args.row_group_size)
        else:
            config = ExperimentConfig(max_rows=args.max_rows, batch_size=args.batch_size,
                max_train_rows=args.max_train_rows, train_fraction=args.train_fraction,
                seed=args.seed, contamination=args.contamination, n_estimators=args.n_estimators,
                statistical_threshold=args.threshold, statistical_quantile=args.threshold_quantile,
                gap_factor=args.gap_factor, point_tolerance_cadences=args.point_tolerance_cadences,
                unlabelled_policy=args.unlabelled_policy, start=args.start, end=args.end,
                features=FeatureConfig(window_samples=args.window_samples, scales=tuple(args.scales),
                                       max_history_rows=args.max_history_rows))
            result = run_experiment(root, args.store, args.output, channels=channels, config=config)
    atomic_json(args.output / f"{args.command}_resources.json", monitor.measurements)
    print(json.dumps({"command": args.command, "status": result["status"],
                      "output": str(args.output.resolve()), "resources": monitor.measurements}))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
