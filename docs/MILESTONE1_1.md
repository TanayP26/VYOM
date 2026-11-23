# Milestone 1.1 — anomaly intelligence and scientific validation

Completed the requested bounded investigation and validation on 22 November 2026. No full 76-channel anomaly benchmark was run. Original source data, Milestone 1 pilot artifacts, `.env`, frontend, chatbot and existing API modules were preserved.

## Root causes established before changing models

**Channel 12:** the signal has only 13 distinct training values. Its local MAD is zero in 89.657% of training rows and 5,164 of the 6,000 diagnostic test rows. An ordinary training step of about 0.001559883 was divided by an epsilon-scale denominator, producing a score near 1,560 against a threshold of six. Of 1,818 statistical alerts, 1,806 occurred with zero MAD. Isolation Forest contributed zero additional flags in that diagnostic. Exact causal MAD was mathematically correct; the numerical scale floor was inappropriate for quantized telemetry.

The detector also adapted to sustained anomalies and ignored its longer-scale score. Closing events on each negative sample fragmented the flags into 783 events. One-to-one matching correctly credited only one truth event: the remaining 782 comprise **64 redundant overlaps and 718 events wholly outside the annotation**. These are now separate burden categories.

**Channel 61:** the annotated point exists exactly at `2007-04-15T00:41:23.373Z`. Its value changes from 0.982790 to 0.508518 following a 60,065.511-second gap. That gap empties the 7.5-hour short window, sets `feature_valid=0`, and causes both baseline detectors to abstain. The unused 30-hour feature had a score of 474,272.25. This was a history-gating defect, not a point-label/tolerance mismatch.

Evidence, reproducible investigation and primary-source methodology review: [M11_ROOT_CAUSES.md](M11_ROOT_CAUSES.md).

## Implemented changes

- Causal sampling-regime tracking with eight-observation confirmation, local cadence, delayed resolution of isolated gap candidates, segment durations and explicit confirmation latency. Timestamps remain unchanged. The full-time sampling scan covered only the five already ingested channels.
- Separate point/change and persistent interval/drift scores. Training learns robust and quantization-aware scale floors. The point path keeps a bounded prior-observation reference across gaps and discloses its age. Persistent scores use multiple causal durations and a training reference.
- Independent chronological training, validation calibration and final scoring. A fixed 1% validation score-tail budget, minimum score threshold of three, persistence, hysteresis and grouping settings are recorded before final scoring. No final-label optimization was performed.
- Primary 60/20/20 and secondary 50/20/30 splits. The latter subdivides M1's original 70% development prefix and retains the exact original 6,000-row holdout. Both are reported; no preferred split is selected using final metrics.
- Six univariate candidates: robust statistical, Isolation Forest, point, interval, temporal union and corroborated combined detector. Four additional aligned cases include PCA alongside the same comparators. RF is skipped because these training windows lack positive annotated events and independently confirmed negative examples.
- Local-cadence point tolerance, one-to-one matching, original IDs, duration/peak evidence, category and point/interval views. Reports separate annotation-supported recall, alert burden, redundant overlaps, outside-label alerts and assumed-normal precision/F1/false alarms.
- Frozen per-case configuration manifests, models, validation scores, final predictions, event JSONL, code/artifact hashes, measured resources and resumable completed cases. The comparison runner caps each selected window at 100,000 rows and has no full-benchmark mode.

The new runner uses the existing ingestion store, causal baseline features, model implementations, annotation loading and evaluation components. It extends the current backend; it does not create another application or environment. The dashboard/API still uses the M1 path. Candidate models are exposed through the comparison CLI pending broader validation, without changing API contracts or chatbot/frontend behavior.

## Before/after measured results

These rows use the same original final observation windows. M1 trained on 70%; M1.1 uses 50% training and 20% validation. Point/interval/combined strategies were declared before final scoring. The new temporal union and combined detector have identical positive-window metrics here.

| Diagnostic | Metric | Original M1 combined | M1.1 temporal union |
|---|---|---:|---:|
| Channel 12 interval | Sample precision | 0.035754 | 0.774368 |
| | Sample recall | 0.150812 | 0.995360 |
| | Sample F1 | 0.057803 | 0.871066 |
| | Event precision | 0.001277 | 0.023256 |
| | Event recall | 1.000000 | 1.000000 |
| | Event F1 | 0.002551 | 0.045455 |
| | Unmatched events | 782 | 42 |
| Channel 61 point | Sample precision | 0 | 0.500000 |
| | Sample recall | 0 | 1.000000 |
| | Sample F1 | 0 | 0.666667 |
| | Event precision / recall / F1 | 0 / 0 / 0 | 0.5 / 1 / 0.666667 |
| | Unmatched events | 20 | 1 |

The interval-specific candidate is especially useful in the interval diagnostic: sample F1 is **0.903704**, with one matched event and three redundant overlapping events; none of its four events is wholly outside the truth interval. It misses the point, which validates keeping the strategies separate. The point strategy detects the channel 61 event but retains one outside-label alert. These are measured case outcomes, not a policy for choosing the best model after seeing each test label.

The combined detector is not universally better. In the channel 74 prefix under 50/20/30, it emits 262 events, compared with 97 for temporal union and two for the statistical candidate. There are no positive labels in that prefix holdout, so detection recall cannot be assessed. PCA's aligned prefix tests also lack positive truth. Full per-candidate results, identical ranges, precision/recall/F1, false alarms/day, runtime and memory: [M11_DETECTION_COMPARISON.md](M11_DETECTION_COMPARISON.md).

## Ground-truth interpretation

The official preparation code initializes unannotated observations to nominal and overlays the annotations. It explicitly states that training is not guaranteed normal. Nominal complement is therefore a verified **benchmark convention**, not proof of error-free physical normality. Target=NO remains contextual/unlabelled; it never becomes a negative class. [Official Mission 1 preparation](https://raw.githubusercontent.com/kplabs-pl/ESA-ADB/main/notebooks/data-prep/Mission1_semisupervised_prep_from_raw.py)

Annotation-supported recall is reported independently from assumption-dependent precision/F1/false-alarm rates. The official ESA metric separates redundant alarming and uses corrected precision/affiliation measures; this milestone retains VYOM's explicitly named one-to-one overlap F1 and does not claim leaderboard equivalence. [Official ESA metric implementation](https://raw.githubusercontent.com/kplabs-pl/ESA-ADB/main/timeeval/metrics/ESA_ADB_metrics.py)

The diagnostics and their labels were examined during M1 and the requested forensic investigation. Although final partitions are excluded from fitting and calibration, they are **development-exposed regression diagnostics**, not a newly unseen external test set. Under primary 60/20/20, the channel 61 point lies in validation and its final partition contains no positive truth; its final recall is correctly unavailable. The secondary split preserves the original point holdout and reports that event separately.

## Sampling and measured resources

| Channel | Confirmed sampling segments | Cadences observed in confirmed segments |
|---|---:|---|
| 1 | 471 | 3, 90, 450, 900 seconds |
| 12 | 90 | 0.375, 3, 90, 180, 360 seconds |
| 41 | 33 | 3, 30, 600 seconds |
| 61 | 1 | 900 seconds |
| 74 | 6 | 3, 6, 30 seconds |

These are inferred segments under the declared confirmation rule, not verified spacecraft modes. Every segment has confirmed/effective start, end, duration, observation count and confirmation lag. Detailed report: [M11_SAMPLING_REGIMES.md](M11_SAMPLING_REGIMES.md).

| Operation | Scope | Wall time | Sampled peak process RSS |
|---|---|---:|---:|
| Sampling-regime profiling | 59,926,812 timestamps; five channels | 46.457 s | 154.469 MiB |
| Final comparison | 18 cases; 112 candidate comparisons | 34.197 s | 210.191 MiB |
| Verified comparison resume | All 18 completed cases reused | 0.224 s | 194.777 MiB |

RSS includes native libraries and is sampled every 50 ms, so brief peaks may be missed. Per-model times in the comparison report sum their measured dependency stages, with shared features reused; they are not isolated process benchmarks. The 18 cases include 14 unresampled 20,000-row cases and four 2,000-row aligned PCA cases. No GPU or new dependency was installed.

## Files added and execution

Existing application modules, requirements, `.env` and old pilot outputs were not overwritten. New files:

```text
backend/app/cadence.py
backend/app/temporal.py
backend/app/calibration.py
backend/app/scientific.py
backend/app/comparison.py
backend/scripts/investigate_m11.py
backend/scripts/profile_regimes.py
backend/scripts/report_m11.py
backend/tests/test_cadence.py
backend/tests/test_temporal_detection.py
backend/tests/test_calibration.py
backend/tests/test_scientific.py
backend/tests/test_comparison.py
docs/MILESTONE1_1.md
docs/M11_ROOT_CAUSES.md
docs/M11_SAMPLING_REGIMES.md
docs/M11_DETECTION_COMPARISON.md
docs/M11_CALIBRATION.md
docs/M11_EVENT_EVALUATION.md
```

Run in the existing working environment:

```powershell
Set-Location 'D:\Projects\VYOM\VYOM\backend'
.\.venv\Scripts\python.exe scripts/investigate_m11.py
.\.venv\Scripts\python.exe scripts/profile_regimes.py
.\.venv\Scripts\python.exe -m app.comparison
.\.venv\Scripts\python.exe scripts/report_m11.py
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

Comparison defaults to `artifacts/milestone11/comparison_final`. Repeating its identical command verifies hashes and resumes completed cases. Use a new `--output` directory if code/configuration changes. Sampling reports are under `artifacts/milestone11/regimes`; they supplement the preserved M1 profile. Configuration evidence is in each case's `model_configuration.json`, `threshold_calibration.json` and `validation_scores.parquet`, referenced by [the comparison manifest](../artifacts/milestone11/comparison_final/manifest.json).

## Verification and remaining limitations

Final suite: **108 passed in 17.60 seconds**, with four existing deprecation warnings. `pip check` reports no broken requirements. New tests cover cadence switches/jitter/gaps, batch/future invariance, local point tolerance, train/validation/test boundaries, calibration exclusion of test data, quantized signals, post-gap points, persistent drift, history budgets, event bridging, duplicate burden and the bounded comparison workflow.

An intermediate integrated run hit a transient Windows/Python 3.14 joblib thread-pool shutdown error in the unchanged legacy RF test. That test passed in isolation and the subsequent complete 108-test run passed. No dependency or legacy RF setting was changed to mask it; it remains an environment reliability observation. The first comparison attempt also exposed NaN propagation when IF abstained at a post-gap point. That integration defect was fixed, a regression test was added, and the successful final comparison was run into a new directory. The failed attempt remains separate for audit; thresholds were not retuned against its results.

Preservation checks verified 63 protected file hashes and all 778 original source size/mtime records. Original pilots, frontend, `.env`, chatbot and API/database files are unchanged. Model/configuration/artifact hashes of the final cases were checked on resume. [Test report](../artifacts/milestone11/verification/tests.xml) · [Preservation verification](../artifacts/milestone11/verification/preservation_after.json).

Remaining limits:

- No full benchmark or external blind holdout validation; no production-readiness claim. No candidate was activated in the dashboard.
- Model improvements vary across channels and anomaly types. The temporal union still has 42 unmatched interval-diagnostic events; IF can increase burden. Rare Event and Communication Gap support is sparse or absent in these short windows.
- Persistent intervals still fragment; point comparisons after a gap use stale historical values and may flag legitimate state changes. Gap candidates do not establish a communication failure.
- Cadence transitions require confirmation. Short or periodic timing bursts and slow changes may remain uncertain; terminal candidates can be unresolved. Only five full channel timelines were profiled for regimes.
- Temporal history is capped at 4,096 observations. Dense windows expose `truncated_history`; they do not claim an exact unlimited-duration baseline. Longer mission regimes may require budget/context choices and further validation.
- PCA uses two channels sharing an anonymous unit with explicit causal resampling, but their physical correlation is not established. Its current final windows lack positive events. RF was not trained on manufactured labels.
- Source ground truth can contain omissions/boundary uncertainty. Separate supported-recall and assumed-normal views remain necessary. This is not the official ESA metric implementation.

Additional reports: [calibration](M11_CALIBRATION.md) and [event evaluation](M11_EVENT_EVALUATION.md). Work stops at this representative-channel validation boundary, as requested.
