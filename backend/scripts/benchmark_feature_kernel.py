import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.features import FeatureConfig, TemporalFeatureBuilder

ROWS = 120_000
idx = pd.date_range("2000-01-01", periods=ROWS, freq="375ms", tz="UTC")
rng = np.random.default_rng(7)
series = pd.Series(rng.normal(size=ROWS), index=idx)

cfg = FeatureConfig(
    window_samples=30,
    scales=(1,),
    min_periods=5,
    max_history_rows=50000,
    block_size=512,
)

builder = TemporalFeatureBuilder(90.0, cfg)
started = time.perf_counter()
frame = builder.transform(series)
elapsed = time.perf_counter() - started

print("rows:", len(frame))
print("seconds:", round(elapsed, 3))
print("rows_per_second:", round(len(frame) / elapsed, 1))
print("peak_history_count:", int(frame.history_count.max()))
print("feature_valid:", int(frame.feature_valid.sum()))
