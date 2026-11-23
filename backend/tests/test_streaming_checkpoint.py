"""Transactional fragment publication and deterministic checkpoint recovery."""
import json

import pandas as pd
import pytest

from app.streaming_checkpoint import FragmentJournal


IDENTITIES = {name: char * 64 for name, char in zip(
    ("source", "code", "config", "protocol"), "abcd")}


def _frame():
    index = pd.date_range("2000", periods=4, freq="30s", tz="UTC")
    return pd.DataFrame({"score": [1., 2., 3., 4.]}, index=index)


def test_fragment_chain_round_trip_and_corruption_detection(tmp_path):
    journal = FragmentJournal(tmp_path, IDENTITIES)
    journal.commit({"stage": "score", "cursor": 4}, frames={"predictions": _frame()},
                   events=[{"start": "2000-01-01T00:00:00Z", "end": "2000-01-01T00:00:00Z"}])
    assert FragmentJournal(tmp_path, IDENTITIES).load()["cursor"] == 4
    assert pd.concat(frame for _, frame in journal.frames("predictions")).score.tolist() == [1., 2., 3., 4.]
    event_path = next(path for _, path, _ in journal.fragments("events"))
    data = bytearray(event_path.read_bytes())
    data[0] ^= 1
    event_path.write_bytes(data)
    with pytest.raises(ValueError, match="Corrupted committed fragment"):
        FragmentJournal(tmp_path, IDENTITIES).load()


def test_identity_change_is_rejected(tmp_path):
    FragmentJournal(tmp_path, IDENTITIES).commit({"stage": "fit", "cursor": 0})
    with pytest.raises(ValueError, match="identity changed"):
        FragmentJournal(tmp_path, {**IDENTITIES, "config": "f" * 64}).load()


@pytest.mark.parametrize("fault_stage,committed", [("after_fragments", False),
                                                     ("after_state", False),
                                                     ("before_pointer", False),
                                                     ("after_pointer", True)])
def test_interrupted_commit_has_single_deterministic_recovery_point(tmp_path, fault_stage, committed):
    first = FragmentJournal(tmp_path, IDENTITIES)
    first.commit({"stage": "score", "cursor": 4}, frames={"predictions": _frame()})
    raised = False

    def fail(stage):
        nonlocal raised
        if stage == fault_stage and not raised:
            raised = True
            raise KeyboardInterrupt(stage)

    interrupted = FragmentJournal(tmp_path, IDENTITIES, fail)
    assert interrupted.load()["cursor"] == 4
    with pytest.raises(KeyboardInterrupt):
        interrupted.commit({"stage": "score", "cursor": 8}, frames={"predictions": _frame()})
    recovered = FragmentJournal(tmp_path, IDENTITIES)
    assert recovered.load()["cursor"] == (8 if committed else 4)
    if not committed:
        recovered.commit({"stage": "score", "cursor": 8}, frames={"predictions": _frame()})
    assert recovered.load()["cursor"] == 8
    assert sum(meta["rows"] for _, _, meta in recovered.fragments("predictions")) == 8


def test_broken_generation_chain_is_rejected(tmp_path):
    journal = FragmentJournal(tmp_path, IDENTITIES)
    journal.commit({"stage": "a", "cursor": 1})
    journal.commit({"stage": "b", "cursor": 2})
    path = tmp_path / "generation-00000001.json"
    value = json.loads(path.read_text())
    value["previous_sha256"] = "0" * 64
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="chain is broken"):
        FragmentJournal(tmp_path, IDENTITIES).load()
