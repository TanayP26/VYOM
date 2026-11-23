# Measured pilot and validation results

Measured on the supplied local Windows environment, 22 November 2026. All results below are observed artifacts; no full-dataset model performance is claimed.

| Operation | Coverage | Wall time (s) | Sampled peak RSS (MiB) |
|---|---|---:|---:|
| Read-only profile | 76 channels; 744,856,895 rows | 40.182 | 559.766 |
| Parquet ingestion | 5 channels; 59,926,812 rows | 8.493 | 663.227 |
| Prefix analysis | 5 x 20,000 rows; 30,000 held out | 8.192 | 239.273 |
| Analysis resume | 5 completed channels verified and skipped | 0.835 | 193.895 |

The CLI separately measured the original analysis at 8.196 s / 239.273 MiB and resume at 0.839 s / 193.895 MiB. The table uses the experiment-internal monitor for analysis/resume. These are absolute process RSS measurements, sampled every 50 ms; very brief peaks may be missed. Each measurement includes native NumPy/Arrow/sklearn allocations. Runs used CPU, batches of 5,000, a training-sample cap of 10,000 and 100 IF trees. Five ingested Parquet files occupy 471,802,701 bytes (449.95 MiB).

Each prefix analysis selected 20,000 chronological rows, trained on the first 14,000, and evaluated the next 6,000. There were no positive value annotations in those held-out prefix windows, so they cannot establish anomaly recall. `assume_normal` was explicit for annotated channels; channel 1 remained unlabelled and had no supervised metric estimates.

| Channel | Training cadence (s) | Analysis (s) | Peak RSS (MiB) | Combined held-out candidate events | Ground-truth value events |
|---|---:|---:|---:|---:|---:|
| channel_1 | 90 | 1.361 | 212.621 | 1 | 0 |
| channel_12 | 90 | 1.445 | 222.309 | 799 | 0 |
| channel_41 | 30 | 1.450 | 229.773 | 81 | 0 |
| channel_61 | 900 | 1.351 | 234.535 | 21 | 0 |
| channel_74 | 3 | 1.415 | 238.430 | 211 | 0 |

## Positive-annotation diagnostics

These two windows were deliberately selected to include known annotations in their held-out portions. They exercise real interval and point handling, but are selection-biased diagnostics. No model or threshold was adjusted after seeing their test results.

| Diagnostic | Truth | Sample TP / FP / FN | Sample precision / recall / F1 | Event TP / FP / FN | Event precision / recall / F1 | False alarms/day |
|---|---|---|---|---|---|---:|
| Interval: channel_12 | 1 | 65 / 1753 / 366 | 0.035754 / 0.150812 / 0.057803 | 1 / 782 / 0 | 0.001277 / 1.000000 / 0.002551 | 134.785429 |
| Point: channel_61 | 1 | 0 / 300 / 1 | 0.000000 / 0.000000 / 0.000000 | 0 / 20 / 1 | 0.000000 / 0.000000 / 0.000000 | 0.320191 |

The interval diagnostic matched `id_167` once despite many detections inside the same truth interval. It also produced 782 unmatched events, counted as false alarms under the explicit assumed-normal policy. The point diagnostic retained `id_116`, used a 450-second tolerance, and recorded one false negative: it did not detect that point. This baseline needs further training-only calibration/model development before operational alerting.

## Verification

- Final pytest run: **82 passed in 12.01 s**, four deprecation warnings; [JUnit XML](../artifacts/verification/tests.xml).
- `pip check`: no broken requirements.
- Real analysis resume verified artifact hashes and skipped all five completed channels. Synthetic tests additionally corrupt artifacts and interrupt a channel to validate recovery.
- Held-out-tail mutation tests prove training features, model bytes and thresholds remain unchanged when only future values change.
- Isolated SQLite/API integration verifies event fields, annotation IDs, publication idempotence and existing GET response contracts.
- Original source inventory: all 778 size/mtime records unchanged. `.env` and frontend SHA256 hashes unchanged. [Preservation verification](../artifacts/verification/preservation_after.json).
- No notebook was found inside the workspace. No notebook or production database was modified. Frontend code was preserved and was not browser-tested/rebuilt.

## Artifacts

- [Full profile](../artifacts/profile/dataset_profile.json)
- [Five-channel ingestion manifest](../artifacts/telemetry/manifest.json)
- [Prefix pilot manifest](../artifacts/pilot/manifest.json)
- [Interval diagnostic manifest](../artifacts/pilot_annotation_interval/manifest.json)
- [Point diagnostic manifest](../artifacts/pilot_annotation_point/manifest.json)
- Channel folders contain `report.json`, `features.json`, feature Parquet, held-out predictions Parquet, models and streamed `events.jsonl`.

The complete 76-channel ingestion and benchmark analysis remain unexecuted. Installation, exact full-run commands, matching protocol and limitations are in [MILESTONE1.md](MILESTONE1.md).
