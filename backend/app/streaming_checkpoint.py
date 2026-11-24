"""Transactional, hash-chained output fragments and one bounded current state."""
from __future__ import annotations

import json
import os
from pathlib import Path
import time

import pandas as pd

from app.artifacts import file_sha256
from app.storage import atomic_json, atomic_replace
from app.streaming_state import encode_state, decode_state


def atomic_bytes(path, payload):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".partial")
    with temporary.open("wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    atomic_replace(temporary, path)


class FragmentJournal:
    """Pointer commits last. Uncommitted generations are overwritten on retry.

    Metadata is visited one generation at a time, never collected in a growing
    in-memory list. Only the current state is retained after a successful commit.
    Prediction/event fragments and their chain remain immutable and verifiable.
    The caller must hold the channel's run_lock.
    """
    def __init__(self, directory, identities, fault=None):
        self.root = Path(directory).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.identities = identities
        self.fault = fault or (lambda _: None)
        self.pointer_path = self.root / "checkpoint.json"
        self.pointer = None
        self.commit_seconds = 0.

    def _path(self, name):
        path = (self.root / name).resolve()
        if path.parent != self.root:
            raise ValueError("Checkpoint artifact outside channel journal")
        return path

    def load(self):
        if not self.pointer_path.exists():
            return None
        pointer = json.loads(self.pointer_path.read_text())
        if pointer["identities"] != self.identities:
            raise ValueError("Source/code/config/protocol identity changed; new namespace required")
        previous = None
        for generation in range(pointer["generation"] + 1):
            path = self._path(f"generation-{generation:08d}.json")
            entry = json.loads(path.read_text())
            if entry["generation"] != generation or entry["previous_sha256"] != previous:
                raise ValueError("Checkpoint generation chain is broken")
            for artifact in entry["fragments"]:
                target = self._path(artifact["path"])
                if file_sha256(target) != artifact["sha256"]:
                    raise ValueError(f"Corrupted committed fragment: {target.name}")
            previous = file_sha256(path)
        if previous != pointer["generation_sha256"]:
            raise ValueError("Committed generation hash mismatch")
        state_path = self._path(pointer["state_path"])
        if file_sha256(state_path) != pointer["state_sha256"]:
            raise ValueError("Checkpoint state hash mismatch")
        self.pointer = pointer
        state = decode_state(state_path.read_bytes(), self.identities)
        # A crash after pointer publication can leave an older state copy. The
        # immutable fragment/generation chain stays; only superseded state is
        # removed after the current pointer and current state have verified.
        for orphan in self.root.glob("generation-*-state.bin"):
            if orphan != state_path:
                orphan.unlink()
        return state

    def commit(self, state, *, frames=None, events=None, json_values=None):
        started = time.perf_counter()
        old = self.pointer
        generation = 0 if old is None else old["generation"] + 1
        prefix = f"generation-{generation:08d}"
        fragments = []
        for kind, frame in (frames or {}).items():
            path = self._path(f"{prefix}-{kind}.parquet")
            temporary = path.with_suffix(".partial")
            frame = frame.copy(deep=False)
            frame.index.name = "timestamp"
            frame.to_parquet(temporary, engine="pyarrow", compression="zstd", row_group_size=max(1, len(frame)))
            with temporary.open("r+b") as stream:
                os.fsync(stream.fileno())
            atomic_replace(temporary, path)
            fragments.append({"kind": kind, "path": path.name, "sha256": file_sha256(path), "rows": len(frame), "bytes": path.stat().st_size})
        if events is not None:
            path = self._path(f"{prefix}-events.jsonl")
            atomic_bytes(path, b"".join((json.dumps(event, default=str, allow_nan=False) + "\n").encode() for event in events))
            fragments.append({"kind": "events", "path": path.name, "sha256": file_sha256(path), "rows": len(events), "bytes": path.stat().st_size})
        for kind, value in (json_values or {}).items():
            path = self._path(f"{prefix}-{kind}.json")
            atomic_json(path, value)
            fragments.append({"kind": kind, "path": path.name, "sha256": file_sha256(path), "bytes": path.stat().st_size})
        self.fault("after_fragments")
        state_path = self._path(f"{prefix}-state.bin")
        atomic_bytes(state_path, encode_state(state, self.identities))
        self.fault("after_state")
        meta = {"generation": generation, "previous_sha256": None if old is None else old["generation_sha256"],
                "stage": state["stage"], "cursor": state.get("cursor"), "fragments": fragments}
        meta_path = self._path(f"{prefix}.json")
        atomic_json(meta_path, meta)
        pointer = {"schema_version": 1, "identities": self.identities, "generation": generation,
                   "generation_sha256": file_sha256(meta_path), "state_path": state_path.name,
                   "state_sha256": file_sha256(state_path)}
        self.fault("before_pointer")
        atomic_json(self.pointer_path, pointer)
        self.pointer = pointer
        self.fault("after_pointer")
        if old is not None:
            self._path(old["state_path"]).unlink(missing_ok=True)
        self.commit_seconds += time.perf_counter() - started

    def fragments(self, kind, stop_generation=None):
        if self.pointer is None:
            return
        stop = self.pointer["generation"] if stop_generation is None else stop_generation
        for generation in range(stop + 1):
            entry = json.loads(self._path(f"generation-{generation:08d}.json").read_text())
            for artifact in entry["fragments"]:
                if artifact["kind"] == kind:
                    yield generation, self._path(artifact["path"]), artifact

    def frames(self, kind, stop_generation=None):
        for generation, path, _ in self.fragments(kind, stop_generation):
            yield generation, pd.read_parquet(path)

    def storage_metrics(self):
        counts = {"prediction_bytes": 0, "prefix_bytes": 0, "event_bytes": 0, "checkpoint_bytes": 0}
        for path in self.root.iterdir():
            if not path.is_file():
                continue
            name = path.name
            key = ("prediction_bytes" if name.endswith("-predictions.parquet") else
                   "prefix_bytes" if name.endswith("-prefix.parquet") else
                   "event_bytes" if name.endswith("-events.jsonl") else "checkpoint_bytes")
            counts[key] += path.stat().st_size
        return counts
