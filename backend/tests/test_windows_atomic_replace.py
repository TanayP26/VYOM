import json
import os

import pytest

from app.storage import atomic_json, atomic_replace
from app.streaming_checkpoint import atomic_bytes


def _denied():
    exc = PermissionError(13, "Access is denied")
    try:
        exc.winerror = 5
    except Exception:
        pass
    return exc


def test_atomic_replace_retries_transient_permission_error(monkeypatch, tmp_path):
    source = tmp_path / "value.tmp"
    destination = tmp_path / "value.json"
    source.write_text("new", encoding="utf-8")
    destination.write_text("old", encoding="utf-8")

    real = os.replace
    calls = {"count": 0}

    def flaky(src, dst):
        calls["count"] += 1
        if calls["count"] <= 3:
            raise _denied()
        return real(src, dst)

    monkeypatch.setattr(os, "replace", flaky)
    atomic_replace(source, destination, attempts=6, initial_delay=0, max_delay=0)

    assert calls["count"] == 4
    assert destination.read_text(encoding="utf-8") == "new"
    assert not source.exists()


def test_atomic_json_recovers_from_transient_windows_lock(monkeypatch, tmp_path):
    target = tmp_path / "checkpoint.json"
    real = os.replace
    calls = {"count": 0}

    def flaky(src, dst):
        calls["count"] += 1
        if calls["count"] == 1:
            raise _denied()
        return real(src, dst)

    monkeypatch.setattr(os, "replace", flaky)
    atomic_json(target, {"generation": 7})

    assert json.loads(target.read_text(encoding="utf-8")) == {"generation": 7}


def test_atomic_bytes_uses_retrying_publish(monkeypatch, tmp_path):
    target = tmp_path / "state.bin"
    real = os.replace
    calls = {"count": 0}

    def flaky(src, dst):
        calls["count"] += 1
        if calls["count"] <= 2:
            raise _denied()
        return real(src, dst)

    monkeypatch.setattr(os, "replace", flaky)
    atomic_bytes(target, b"abc123")

    assert target.read_bytes() == b"abc123"
    assert calls["count"] == 3


def test_permanent_denial_never_overwrites_committed_destination(monkeypatch, tmp_path):
    source = tmp_path / "next.tmp"
    destination = tmp_path / "checkpoint.json"
    source.write_text("next", encoding="utf-8")
    destination.write_text("committed", encoding="utf-8")

    def always_fail(*_):
        raise _denied()

    monkeypatch.setattr(os, "replace", always_fail)

    with pytest.raises(PermissionError, match="Atomic publish failed"):
        atomic_replace(source, destination, attempts=3, initial_delay=0, max_delay=0)

    assert destination.read_text(encoding="utf-8") == "committed"
    assert source.read_text(encoding="utf-8") == "next"
