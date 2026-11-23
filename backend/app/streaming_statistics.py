"""Exact external order statistics for the frozen M1.1 fitting procedure.

Each sorter keeps bounded sorted runs and uses bounded, vectorized merge buffers.
Input telemetry infinities become missing as in TemporalDetector.fit. Infinities
created by float64 subtraction/absolute-deviation overflow are retained: deleting
those would silently change the frozen numerical semantics.
"""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
import os
from pathlib import Path
import tempfile
import time

import numpy as np
import pandas as pd

from app.calibration import QuantileCalibrator
from app.temporal import TemporalDetector, _series


@dataclass
class _Run:
    path: Path
    rows: int


class _DiskLedger:
    def __init__(self):
        self.current = self.peak = self.written = self.read = 0

    def write(self, size):
        self.current += size
        self.written += size
        self.peak = max(self.peak, self.current)


class ExternalOrderStatistics:
    """A bounded external sorter whose finalized file supports exact selection.

    Numeric working memory is O(run_rows + fan_in*buffer_rows); conversions and
    finite-value masks may coexist with an input chunk. A merge retains at most
    fan_in input buffers and one combined buffer of their total size. Run metadata is tier-compacted, so it
    grows logarithmically in the input count. This class owns only its unique
    scratch directory; close() never removes a caller's existing artifacts.
    """
    def __init__(self, output, run_rows=250_000, fan_in=16, buffer_rows=8192,
                 _ledger=None):
        if run_rows < 1 or buffer_rows < 1 or fan_in < 2:
            raise ValueError("Positive run/buffer sizes and fan_in >= 2 are required")
        self.run_rows, self.fan_in, self.buffer_rows = int(run_rows), int(fan_in), int(buffer_rows)
        output = Path(output)
        output.mkdir(parents=True, exist_ok=True)
        self.directory = Path(tempfile.mkdtemp(prefix="exact-sort-", dir=output))
        self._ledger = _ledger or _DiskLedger()
        self._levels = []
        self._serial = 0
        self._final = None
        self._finished = False
        self._closed = False
        self.count = self.input_rows = self.run_count = self.merge_count = 0
        self.max_run_rows = self.max_merge_input_runs = self.max_merge_buffer_values = 0
        self.max_live_run_metadata = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _new_path(self):
        self._serial += 1
        return self.directory / f"run-{self._serial:012d}.f64"

    def add(self, values, finite_only=True):
        if self._closed or self._finished:
            raise RuntimeError("Cannot add values after sorter finalization/closure")
        values = np.asarray(values)
        if values.ndim != 1:
            raise ValueError("Order-statistic inputs must be one-dimensional")
        self.input_rows += len(values)
        for offset in range(0, len(values), self.run_rows):
            block = np.asarray(values[offset:offset + self.run_rows], dtype=np.float64)
            block = block[np.isfinite(block) if finite_only else ~np.isnan(block)]
            if not len(block):
                continue
            block.sort()
            path = self._new_path()
            with path.open("wb") as stream:
                block.tofile(stream)
            self._ledger.write(block.nbytes)
            self.count += len(block)
            self.run_count += 1
            self.max_run_rows = max(self.max_run_rows, len(block))
            self._insert(_Run(path, len(block)), 0)

    def _insert(self, run, level):
        while len(self._levels) <= level:
            self._levels.append([])
        self._levels[level].append(run)
        self.max_live_run_metadata = max(self.max_live_run_metadata, sum(map(len, self._levels)))
        if len(self._levels[level]) >= self.fan_in:
            inputs, self._levels[level] = self._levels[level], []
            self._insert(self._merge(inputs), level + 1)

    def _merge(self, runs):
        """Merge <=fan_in runs using buffer-frontier selection, not row heaps."""
        destination = self._new_path()
        temporary = destination.with_suffix(".partial")
        self.merge_count += 1
        self.max_merge_input_runs = max(self.max_merge_input_runs, len(runs))
        written = 0
        with ExitStack() as stack:
            handles = [stack.enter_context(run.path.open("rb")) for run in runs]
            writer = stack.enter_context(temporary.open("wb"))
            blocks = [np.fromfile(handle, dtype=np.float64, count=self.buffer_rows) for handle in handles]
            self._ledger.read += sum(block.nbytes for block in blocks)
            while any(len(block) for block in blocks):
                # Nothing after the smallest buffered last value can precede
                # an unseen value in any run. Drain all buffered <= frontier.
                frontier = min(block[-1] for block in blocks if len(block))
                stops = [int(np.searchsorted(block, frontier, side="right")) for block in blocks]
                merged = np.concatenate([block[:stop] for block, stop in zip(blocks, stops) if stop])
                self.max_merge_buffer_values = max(self.max_merge_buffer_values,
                    sum((block.base if isinstance(block.base, np.ndarray) else block).size
                        for block in blocks) + len(merged))
                merged.sort()
                merged.tofile(writer)
                self._ledger.write(merged.nbytes)
                written += len(merged)
                # Release this output before allocating the next one; otherwise
                # assignment's RHS could briefly retain two full merged buffers.
                del merged
                for index, stop in enumerate(stops):
                    blocks[index] = blocks[index][stop:]
                    if not len(blocks[index]):
                        blocks[index] = np.fromfile(handles[index], dtype=np.float64, count=self.buffer_rows)
                        self._ledger.read += blocks[index].nbytes
            writer.flush()
            os.fsync(writer.fileno())
        if written != sum(run.rows for run in runs):
            raise RuntimeError("External merge changed the observation count")
        os.replace(temporary, destination)
        for run in runs:
            run.path.unlink()
            self._ledger.current -= run.rows * 8
        return _Run(destination, written)

    def finish(self):
        if self._closed:
            raise RuntimeError("Sorter is closed")
        if self._finished:
            return self
        runs = [run for level in self._levels for run in level]
        self._levels = []
        while len(runs) > 1:
            runs = [self._merge(runs[start:start + self.fan_in])
                    if len(runs[start:start + self.fan_in]) > 1 else runs[start]
                    for start in range(0, len(runs), self.fan_in)]
        self._final = runs[0] if runs else None
        self._finished = True
        return self

    def _select(self, rank, count=1):
        self.finish()
        if self._final is None or rank < 0 or rank + count > self.count:
            raise ValueError("No observations at requested order statistic")
        with self._final.path.open("rb") as stream:
            stream.seek(rank * 8)
            values = np.fromfile(stream, dtype=np.float64, count=count)
        self._ledger.read += values.nbytes
        return values

    def median(self):
        if not self.count:
            raise ValueError("No observations for median")
        # np.median uses np.mean on its central one/two float64 values. Keeping
        # that operation also preserves finite overflow and signed-zero behavior.
        return float(np.mean(self._select((self.count - 1) // 2, 2 if self.count % 2 == 0 else 1)))

    def quantile_higher(self, q):
        if not 0 <= q <= 1 or not self.count:
            raise ValueError("Quantile requires observations and 0 <= q <= 1")
        rank = int(np.ceil((self.count - 1) * float(q)))
        return float(self._select(rank)[0])

    def iter_values(self):
        self.finish()
        if self._final is None:
            return
        with self._final.path.open("rb") as stream:
            while len(block := np.fromfile(stream, dtype=np.float64, count=self.buffer_rows)):
                self._ledger.read += block.nbytes
                yield block

    def count_above(self, threshold):
        return sum(int(np.count_nonzero(block > threshold)) for block in self.iter_values())

    def metrics(self):
        return {"input_rows": self.input_rows, "retained_rows": self.count,
                "sorted_runs": self.run_count, "merge_operations": self.merge_count,
                "max_run_rows": self.max_run_rows, "max_merge_input_runs": self.max_merge_input_runs,
                "max_merge_buffer_values": self.max_merge_buffer_values,
                "max_live_run_metadata": self.max_live_run_metadata,
                "temporary_peak_bytes": self._ledger.peak,
                "temporary_current_bytes": self._ledger.current,
                "scratch_bytes_written": self._ledger.written, "scratch_bytes_read": self._ledger.read,
                "run_rows_limit": self.run_rows, "fan_in_limit": self.fan_in,
                "buffer_rows_per_input_limit": self.buffer_rows}

    def close(self):
        if self._closed:
            return
        # This uniquely created scratch directory contains only this sorter's
        # files, including any private partial left by a failed merge.
        for path in self.directory.iterdir():
            size = path.stat().st_size
            path.unlink()
            self._ledger.current -= size
        self.directory.rmdir()
        self._closed = True


def _bounded_series_batches(batch_factory, rows):
    for batch in batch_factory():
        if not isinstance(batch, (pd.Series, pd.DataFrame)):
            raise TypeError("Batch factory must yield pandas Series or one-column DataFrames")
        for offset in range(0, len(batch), rows):
            yield batch.iloc[offset:offset + rows]


def fit_temporal_stream(batch_factory, output, config=None, train_end=None,
                        run_rows=250_000, fan_in=16, buffer_rows=8192):
    """Fit the unchanged TemporalDetector via exact bounded external statistics."""
    started = time.perf_counter()
    model = TemporalDetector(config)
    ledger = _DiskLedger()
    options = dict(run_rows=run_rows, fan_in=fan_in, buffer_rows=buffer_rows, _ledger=ledger)
    rows = 0
    first = last = None
    previous = np.nan
    with ExternalOrderStatistics(output, **options) as values, \
            ExternalOrderStatistics(output, **options) as steps, \
            ExternalOrderStatistics(output, **options) as deviations:
        for raw in _bounded_series_batches(batch_factory, run_rows):
            series = _series(raw)
            if last is not None and series.index[0] <= last:
                raise ValueError("Training batches must be strictly chronological")
            if train_end is not None and series.index[-1] > pd.Timestamp(train_end):
                raise ValueError("Training extends beyond the chronological training boundary")
            current = series.to_numpy(dtype=np.float64)
            first = series.index[0] if first is None else first
            last = series.index[-1]
            rows += len(current)
            values.add(current)
            with np.errstate(over="ignore", invalid="ignore"):
                differences = np.abs(np.diff(np.concatenate(([previous], current))))
            steps.add(differences[differences > 0], finite_only=False)
            previous = current[-1]
        if values.count < 30:
            raise ValueError("At least thirty finite training observations are required")
        model.location = values.median()
        for block in values.iter_values():
            with np.errstate(over="ignore", invalid="ignore"):
                deviations.add(np.abs(block - model.location), finite_only=False)
        sigma = float(1.4826 * deviations.median())
        quantum = steps.median() if steps.count else 0.0
        epsilon_floor = model.config.epsilon * max(1., abs(model.location))
        model.floor = max(.5 * quantum, .1 * sigma, epsilon_floor)
        model.global_scale = max(sigma, model.floor)
        model.change_scale = max(quantum, model.floor)
        model.training = {"training_start": first.isoformat(), "training_end": last.isoformat(),
            "training_rows": rows, "training_median": model.location,
            "training_robust_sigma": sigma, "median_positive_training_step": quantum,
            "scale_floor": model.floor, "change_scale": model.change_scale,
            "floor_rule": "max(0.5*median positive adjacent training step, 0.1*training robust sigma, epsilon*level)"}
        model.streaming_resources = {"wall_seconds": time.perf_counter() - started,
            "temporary_peak_bytes": ledger.peak, "scratch_bytes_written": ledger.written,
            "scratch_bytes_read": ledger.read,
            "value_sort": values.metrics(), "step_sort": steps.metrics(), "deviation_sort": deviations.metrics()}
    model.reset_state()
    return model


def calibrate_stream(batch_factory, output, tail_probability=.01, minimum_threshold=3,
                     validation_end=None, run_rows=250_000, fan_in=16, buffer_rows=8192):
    """Return an unchanged QuantileCalibrator fitted by exact higher selection."""
    started = time.perf_counter()
    calibration = QuantileCalibrator(tail_probability, minimum_threshold)
    first = last = None
    with ExternalOrderStatistics(output, run_rows, fan_in, buffer_rows) as values:
        for raw in _bounded_series_batches(batch_factory, run_rows):
            if isinstance(raw, pd.DataFrame):
                if raw.shape[1] != 1:
                    raise ValueError("Calibration takes one score column")
                raw = raw.iloc[:, 0]
            if not raw.index.is_monotonic_increasing or not raw.index.is_unique:
                raise ValueError("Validation scores must be nonempty and chronological")
            if last is not None and raw.index[0] <= last:
                raise ValueError("Validation batches must be strictly chronological")
            if validation_end is not None and raw.index[-1] > pd.Timestamp(validation_end):
                raise ValueError("Calibration includes observations after the validation boundary")
            first = raw.index[0] if first is None else first
            last = raw.index[-1]
            values.add(raw.to_numpy(dtype=np.float64))
        if first is None:
            raise ValueError("Validation scores must be nonempty and chronological")
        if not values.count:
            raise ValueError("No finite validation scores")
        calibration.threshold = max(calibration.minimum_threshold,
                                    values.quantile_higher(1 - calibration.tail_probability))
        calibration.info = {
            "method": "validation empirical upper quantile, higher order statistic",
            "tail_probability": calibration.tail_probability,
            "minimum_threshold": calibration.minimum_threshold,
            "threshold": calibration.threshold, "validation_rows": values.count,
            "validation_start": first.isoformat(), "validation_end": last.isoformat(),
            "validation_exceedance_fraction": float(values.count_above(calibration.threshold) / values.count),
            "labels_used": False, "normality_assumption_for_calibration": False,
            "limitation": "Tail budget is not a guaranteed false-alarm rate; validation can contain anomalies"}
        calibration.streaming_resources = {"wall_seconds": time.perf_counter() - started, **values.metrics()}
    return calibration
