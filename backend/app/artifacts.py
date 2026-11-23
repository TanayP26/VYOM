"""Atomic artifact writes, run locking, and measured process resource usage."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import threading
import time

import psutil


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, allow_nan=False, default=str)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@contextmanager
def run_lock(directory):
    """Windows/Linux advisory lock released by OS even after process termination."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".lock").open("a+b") as handle:
        handle.seek(0)
        if not handle.read(1):
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError(f"Another process is using {directory}") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class ResourceMonitor:
    """Wall time and RSS sampled every 50 ms; includes native Arrow/sklearn memory."""
    def __enter__(self):
        self.started = time.perf_counter()
        self.process = psutil.Process()
        self.initial_rss = self.process.memory_info().rss
        self.peak_rss = self.initial_rss
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._sample, daemon=True)
        self.thread.start()
        return self

    def _sample(self):
        while not self.stop.wait(.05):
            self.peak_rss = max(self.peak_rss, self.process.memory_info().rss)

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join()
        self.peak_rss = max(self.peak_rss, self.process.memory_info().rss)
        self.measurements = {
            "wall_seconds": round(time.perf_counter() - self.started, 3),
            "initial_rss_mib": round(self.initial_rss / 1024**2, 3),
            "peak_sampled_rss_mib": round(self.peak_rss / 1024**2, 3),
            "rss_sample_interval_seconds": .05,
        }


class JsonFormatter(logging.Formatter):
    def format(self, record):
        result = {"timestamp": utc_now(), "level": record.levelname,
                  "logger": record.name, "message": record.getMessage()}
        for name in ("channel", "position", "total", "rows"):
            if hasattr(record, name):
                result[name] = getattr(record, name)
        if record.exc_info:
            result["exception"] = self.formatException(record.exc_info)
        return json.dumps(result)


def configure_logging():
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
