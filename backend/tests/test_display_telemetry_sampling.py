import pandas as pd
from app import service


def test_display_prefix_and_requested_range(tmp_path, monkeypatch):
    path = tmp_path / "channel.parquet"
    timestamps = pd.date_range("2013-01-01", periods=60000, freq="s", tz="UTC")
    pd.DataFrame({"timestamp": timestamps, "value": range(len(timestamps))}).to_parquet(path, index=False)
    monkeypatch.setattr(service, "channel_parquet", lambda _: path)
    prefix = service.telemetry_sample("channel_13", points=100)
    assert prefix["source_rows"] == 60000
    assert prefix["window_rows"] == 2000
    assert prefix["returned"] == 100
    assert prefix["points"][0]["v"] == 0
    assert prefix["points"][-1]["v"] == 1999
    assert prefix["sampling"] == "bounded_prefix"
    result = service.telemetry_sample("channel_13", start=timestamps[49990].isoformat(),
                                      end=timestamps[50010].isoformat(), points=100)
    assert result["returned"] == 21
    assert result["points"][0]["v"] == 49990
    assert result["points"][-1]["v"] == 50010
    assert result["sampling"] == "requested_range"
