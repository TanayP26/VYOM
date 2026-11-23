"""Versioned, hash-bound causal checkpoints without pickle deserialization.

Only explicitly registered application/sklearn types are reconstructed. Arrays,
timestamps, tables and RNGs have tagged encodings; no import names or callable
objects supplied by a checkpoint are executed. This is local artifact integrity,
not authentication: callers must also verify a state file's externally recorded
SHA256 and retain the trusted source/code/config/protocol identities.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import RobustScaler
from sklearn.tree import ExtraTreeRegressor
from sklearn.tree._tree import Tree

from app.cadence import CadenceConfig, SamplingRegimeTracker
from app.calibration import DetectionPolicy, QuantileCalibrator
from app.detectors import BoundedTrainingSampler, IsolationForestDetector, StatisticalDetector
from app.evaluation import EventMetricAccumulator
from app.events import AnnotationMatcher, EventGrouper
from app.features import FeatureConfig, TemporalFeatureBuilder
from app.temporal import TemporalConfig, TemporalDetector, TemporalEventGrouper

STATE_VERSION = 1
MAX_STATE_BYTES = 256 * 1024 * 1024
REQUIRED_IDENTITIES = frozenset({"source", "code", "config", "protocol"})


class StateCompatibilityError(ValueError):
    """Checkpoint belongs to a different implementation or execution contract."""


class StateIntegrityError(ValueError):
    """Checkpoint bytes are incomplete, corrupted, or structurally invalid."""


class StreamingTemporalEventGrouper(TemporalEventGrouper):
    """Preserve frozen event geometry while deferring quiet-end flushes.

    Events are finalized only when a later flagged observation proves that the
    local cadence bridge has been exceeded, or at the true end of the test
    stream. ``_finalized_at`` is an internal ordering marker removed before
    persistence; it never changes detector flags or event geometry.
    """
    def __init__(self, channel, bridge_cadences=2.0):
        super().__init__(channel, bridge_cadences)
        self.finished = False
        self._finalization_times = []

    def update(self, index, flags, scores, cadence_seconds, detector, evidence=None):
        if self.finished:
            raise ValueError("Event stream is finished")
        index = pd.DatetimeIndex(index)
        if index.tz is None or index.hasnans or not index.is_unique or not index.is_monotonic_increasing:
            raise ValueError("Grouping requires ordered unique UTC-aware timestamps")
        if len(index) and self.last_timestamp is not None and index[0] <= self.last_timestamp:
            raise ValueError("Grouping batches overlap")
        flags, scores = np.asarray(flags, bool), np.asarray(scores, float)
        cadences = np.broadcast_to(np.asarray(cadence_seconds, float), (len(index),))
        if (flags.shape != (len(index),) or scores.shape != (len(index),)
                or not np.isfinite(cadences).all() or (cadences <= 0).any()):
            raise ValueError("Invalid grouping arrays")

        result = []
        for i in np.flatnonzero(flags):
            if not np.isfinite(scores[i]):
                raise ValueError("Flagged scores must be finite")
            timestamp = index[i]
            if self.current is not None:
                gap = (timestamp - pd.Timestamp(self.current["end"])).total_seconds()
                if gap > self.bridge_cadences * max(cadences[i], self.last_flag_cadence):
                    for event in self.flush():
                        self._finalization_times.append(timestamp.isoformat())
                        result.append(event)
            if self.current is None:
                self.current = {
                    "channel": self.channel,
                    "start": timestamp.isoformat(),
                    "end": timestamp.isoformat(),
                    "duration_seconds": 0.0,
                    "peak_score": float(scores[i]),
                    "sample_count": 0,
                    "detector": detector,
                    "detectors": [detector],
                    "evidence": {
                        **(evidence or {}),
                        "bridge_cadences": self.bridge_cadences,
                        "peak_timestamp": timestamp.isoformat(),
                    },
                }
            self.current["end"] = timestamp.isoformat()
            self.current["duration_seconds"] = (
                timestamp - pd.Timestamp(self.current["start"])
            ).total_seconds()
            self.current["sample_count"] += 1
            if scores[i] > self.current["peak_score"]:
                self.current["peak_score"] = float(scores[i])
                self.current["evidence"]["peak_timestamp"] = timestamp.isoformat()
            self.last_flag_cadence = cadences[i]

        if len(index):
            self.last_timestamp = index[-1]
        return result

    def finish(self):
        self.finished = True
        finalized_at = self.last_timestamp.isoformat() if self.last_timestamp is not None else None
        result = self.flush()
        for event in result:
            self._finalization_times.append(finalized_at or event["end"])
        return result

    def take_finalization_times(self):
        times = list(self._finalization_times)
        self._finalization_times.clear()
        return times


_TYPES = {}


def register_state_type(cls):
    """Explicit registration by trusted application code, never by input data."""
    key = f"{cls.__module__}.{cls.__qualname__}"
    prior = _TYPES.get(key)
    if prior is not None and prior is not cls:
        raise ValueError(f"State type identity already registered: {key}")
    _TYPES[key] = cls
    return cls


for _type in (CadenceConfig, SamplingRegimeTracker, FeatureConfig, TemporalFeatureBuilder,
              TemporalConfig, TemporalDetector, DetectionPolicy, QuantileCalibrator,
              BoundedTrainingSampler, StatisticalDetector, IsolationForestDetector,
              TemporalEventGrouper, StreamingTemporalEventGrouper, EventGrouper,
              AnnotationMatcher, EventMetricAccumulator, IsolationForest,
              RobustScaler, ExtraTreeRegressor):
    register_state_type(_type)


def _dtype_state(dtype):
    return np.lib.format.dtype_to_descr(np.dtype(dtype))


def _encode(value):
    if value is None or type(value) in (bool, int, str):
        return value
    if isinstance(value, np.generic):
        return {"t": "numpy_scalar", "a": _encode(np.asarray(value))}
    if type(value) is float:
        return {"t": "float", "v": value.hex()}
    if value is pd.NaT:
        return {"t": "nat"}
    if value is pd.NA:
        return {"t": "na"}
    if isinstance(value, pd.Timestamp):
        return {"t": "timestamp", "ns": value.value,
                "tz": str(value.tz) if value.tz is not None else None}
    if isinstance(value, pd.Timedelta):
        return {"t": "timedelta", "ns": value.value}
    if isinstance(value, np.ndarray):
        if value.dtype.hasobject:
            return {"t": "object_array", "shape": list(value.shape),
                    "v": [_encode(x) for x in value.flat]}
        array = np.ascontiguousarray(value)
        return {"t": "array", "dtype": _encode(_dtype_state(array.dtype)),
                "shape": list(value.shape), "data": base64.b64encode(array.tobytes()).decode("ascii")}
    if isinstance(value, pd.DatetimeIndex):
        return {"t": "datetime_index", "v": _encode(value.as_unit("ns").asi8),
                "tz": str(value.tz) if value.tz is not None else None,
                "name": _encode(value.name), "freq": value.freqstr, "unit": value.unit}
    if isinstance(value, pd.RangeIndex):
        return {"t": "range_index", "start": value.start, "stop": value.stop,
                "step": value.step, "name": _encode(value.name)}
    if isinstance(value, pd.Index):
        if isinstance(value, pd.MultiIndex):
            raise TypeError("MultiIndex is not part of the frozen benchmark schema")
        return {"t": "index", "v": _encode(value.to_numpy()),
                "name": _encode(value.name), "dtype": str(value.dtype)}
    if isinstance(value, pd.Series):
        if isinstance(value.dtype, pd.DatetimeTZDtype):
            data = _encode(pd.DatetimeIndex(value.array))
        else:
            data = _encode(value.to_numpy())
        return {"t": "series", "v": data, "index": _encode(value.index),
                "name": _encode(value.name), "dtype": str(value.dtype)}
    if isinstance(value, pd.DataFrame):
        return {"t": "frame", "index": _encode(value.index), "columns": _encode(value.columns),
                "v": [_encode(value.iloc[:, i]) for i in range(value.shape[1])]}
    if isinstance(value, np.random.Generator):
        return {"t": "generator", "bit_generator": type(value.bit_generator).__name__,
                "state": _encode(value.bit_generator.state)}
    if isinstance(value, np.random.RandomState):
        return {"t": "random_state", "state": _encode(value.get_state())}
    if isinstance(value, Tree):
        return {"t": "sklearn_tree", "args": _encode(value.__reduce__()[1]),
                "state": _encode(value.__getstate__())}
    if type(value) in (list, tuple, set, frozenset):
        return {"t": type(value).__name__, "v": [_encode(x) for x in value]}
    if type(value) is dict:
        return {"t": "dict", "v": [[_encode(k), _encode(v)] for k, v in value.items()]}
    key = f"{type(value).__module__}.{type(value).__qualname__}"
    if _TYPES.get(key) is type(value):
        return {"t": "registered", "class": key, "state": _encode(vars(value))}
    raise TypeError(f"Unsupported checkpoint state type: {type(value).__module__}.{type(value).__name__}")


def _array_shape(value):
    shape = value["shape"]
    if not isinstance(shape, list) or any(type(n) is not int or n < 0 for n in shape):
        raise StateIntegrityError("Invalid array shape")
    return tuple(shape)


def _decode(value):
    if value is None or type(value) in (bool, int, str):
        return value
    if not isinstance(value, dict) or "t" not in value:
        raise StateIntegrityError("Malformed tagged state")
    tag = value["t"]
    if tag == "float":
        return float.fromhex(value["v"])
    if tag == "nat":
        return pd.NaT
    if tag == "na":
        return pd.NA
    if tag == "timestamp":
        result = pd.Timestamp(value["ns"], unit="ns", tz="UTC" if value["tz"] else None)
        return result.tz_convert(value["tz"]) if value["tz"] else result
    if tag == "timedelta":
        return pd.Timedelta(value["ns"], unit="ns")
    if tag == "array":
        dtype = np.lib.format.descr_to_dtype(_decode(value["dtype"]))
        if dtype.hasobject:
            raise StateIntegrityError("Raw object array pointers are forbidden")
        data = base64.b64decode(value["data"], validate=True)
        shape = _array_shape(value)
        if math.prod(shape) * dtype.itemsize != len(data):
            raise StateIntegrityError("Array bytes do not match dtype/shape")
        return np.frombuffer(data, dtype=dtype).reshape(shape).copy()
    if tag == "object_array":
        shape = _array_shape(value)
        if math.prod(shape) != len(value["v"]):
            raise StateIntegrityError("Object array size differs from shape")
        result = np.empty(len(value["v"]), dtype=object)
        for i, item in enumerate(value["v"]):
            result[i] = _decode(item)
        return result.reshape(shape)
    if tag == "numpy_scalar":
        return _decode(value["a"])[()]
    if tag == "datetime_index":
        result = pd.to_datetime(_decode(value["v"]), unit="ns", utc=bool(value["tz"]))
        if value["tz"]:
            result = result.tz_convert(value["tz"])
        return pd.DatetimeIndex(result, name=_decode(value["name"]), freq=value["freq"]).as_unit(value["unit"])
    if tag == "range_index":
        return pd.RangeIndex(value["start"], value["stop"], value["step"], name=_decode(value["name"]))
    if tag == "index":
        return pd.Index(_decode(value["v"]), name=_decode(value["name"]), dtype=value["dtype"])
    if tag == "series":
        return pd.Series(_decode(value["v"]), index=_decode(value["index"]),
                         name=_decode(value["name"]), dtype=value["dtype"])
    if tag == "frame":
        series = [_decode(v) for v in value["v"]]
        frame = pd.concat(series, axis=1) if series else pd.DataFrame(index=_decode(value["index"]))
        frame.index, frame.columns = _decode(value["index"]), _decode(value["columns"])
        return frame
    if tag == "generator":
        generators = {cls.__name__: cls for cls in
                      (np.random.PCG64, np.random.PCG64DXSM, np.random.MT19937,
                       np.random.Philox, np.random.SFC64)}
        if value["bit_generator"] not in generators:
            raise StateCompatibilityError("Unknown random bit generator")
        bit = generators[value["bit_generator"]]()
        bit.state = _decode(value["state"])
        return np.random.Generator(bit)
    if tag == "random_state":
        result = np.random.RandomState()
        result.set_state(_decode(value["state"]))
        return result
    if tag == "sklearn_tree":
        result = Tree(*_decode(value["args"]))
        result.__setstate__(_decode(value["state"]))
        return result
    if tag in {"list", "tuple", "set", "frozenset"}:
        constructors = {"list": list, "tuple": tuple, "set": set, "frozenset": frozenset}
        return constructors[tag](_decode(x) for x in value["v"])
    if tag == "dict":
        return {_decode(k): _decode(v) for k, v in value["v"]}
    if tag == "registered":
        cls = _TYPES.get(value["class"])
        if cls is None:
            raise StateCompatibilityError(f"Unregistered checkpoint class: {value['class']}")
        state = _decode(value["state"])
        if not isinstance(state, dict) or any(not isinstance(k, str) for k in state):
            raise StateIntegrityError("Object state must be a named-attribute mapping")
        instance = object.__new__(cls)
        instance.__dict__.update(state)
        return instance
    raise StateIntegrityError(f"Unknown state tag: {tag}")


def _validate_identities(identities):
    if not isinstance(identities, dict) or not REQUIRED_IDENTITIES.issubset(identities):
        raise StateCompatibilityError("Required identity hashes: source, code, config, protocol")
    if any(not isinstance(value, str) or len(value) != 64 or
           any(char not in "0123456789abcdef" for char in value) for value in identities.values()):
        raise StateCompatibilityError("Execution identities must be lowercase SHA256 strings")


def encode_state(payload, identities, *, max_bytes=MAX_STATE_BYTES):
    """Encode a bounded state; callers commit it with output fragments atomically."""
    _validate_identities(identities)
    data = json.dumps(_encode(payload), ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    header = {"version": STATE_VERSION, "identities": identities,
              "payload_bytes": len(data), "payload_sha256": hashlib.sha256(data).hexdigest()}
    result = json.dumps(header, sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n" + data
    if len(result) > max_bytes:
        raise ValueError(f"Checkpoint exceeds explicit {max_bytes}-byte state budget")
    return result


def decode_state(blob, expected_identities, *, max_bytes=MAX_STATE_BYTES):
    """Check byte integrity and all contract hashes before reconstructing state."""
    _validate_identities(expected_identities)
    if not isinstance(blob, bytes) or len(blob) > max_bytes:
        raise StateIntegrityError("Invalid or oversized checkpoint")
    try:
        header_bytes, data = blob.split(b"\n", 1)
        header = json.loads(header_bytes)
        if header["version"] != STATE_VERSION:
            raise StateCompatibilityError("Checkpoint schema version differs")
        if header["identities"] != expected_identities:
            raise StateCompatibilityError("Checkpoint source/code/config/protocol identities differ")
        if header["payload_bytes"] != len(data) or header["payload_sha256"] != hashlib.sha256(data).hexdigest():
            raise StateIntegrityError("Checkpoint payload hash/size differs")
        return _decode(json.loads(data))
    except (StateCompatibilityError, StateIntegrityError):
        raise
    except (ValueError, KeyError, TypeError, IndexError, AttributeError, OverflowError) as exc:
        raise StateIntegrityError(f"Invalid checkpoint structure: {type(exc).__name__}") from exc


def save_state(path, payload, identities, *, max_bytes=MAX_STATE_BYTES):
    """Atomic state-file helper; full runner commits its generation pointer last."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = encode_state(payload, identities, max_bytes=max_bytes)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".partial", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "version": STATE_VERSION, "identities": dict(identities)}


def load_state(path, expected_identities, *, expected_sha256, max_bytes=MAX_STATE_BYTES):
    """Verify an externally committed SHA before decoding a local state file."""
    path = Path(path)
    if path.stat().st_size > max_bytes:
        raise StateIntegrityError("State file exceeds byte budget")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise StateIntegrityError("State file SHA256 differs from committed checkpoint")
    return decode_state(data, expected_identities, max_bytes=max_bytes)
