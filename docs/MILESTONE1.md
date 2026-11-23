# Milestone 1 — telemetry intelligence engine

Implemented and locally verified on 22 November 2026. The existing application now uses a bounded Parquet/feature/model/event pipeline. The frontend, database schema, original dataset and `backend/.env` were preserved. This directory has no Git metadata, so no commit or Git diff was created. No notebook was found in this workspace; no notebook was created, removed or edited.

## Installation and commands

Run from the existing backend environment. Its working Python is **3.14.3**, not the unrelated root Conda environment. Existing package versions were retained; PyArrow 26.0.1 and psutil 7.2.2 were added.

```powershell
Set-Location 'D:\Projects\VYOM\VYOM\backend'
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

For a new installation, create `backend/.venv` first with a compatible Python, then install the requirements. Do not replace the existing `.env`. Optional settings and defaults are in `.env.example`, which now contains real newline-separated entries.

The exact full **76-channel ingestion** command is:

```powershell
.\.venv\Scripts\python.exe -m app.cli ingest --dataset '../data/esa_adb/mission1/ESA-Mission1' --output '../artifacts/telemetry'
```

The exact full **chronological benchmark evaluation** command is:

```powershell
.\.venv\Scripts\python.exe -m app.cli evaluate --dataset '../data/esa_adb/mission1/ESA-Mission1' --store '../artifacts/telemetry' --output '../artifacts/benchmark_all76' --unlabelled-policy assume_normal
```

This command explicitly treats unannotated periods on labelled Target=YES channels as assumed normal. Target=NO channels remain unlabelled and are excluded from supervised metrics. For an annotation-only evaluation, replace the policy with `exclude` and choose a different output directory: unknown periods then supply no negatives, and event precision/F1/false-alarm rates are unavailable. Neither policy establishes that every unannotated point is truly normal.

**The full ingestion and full benchmark commands above have not been executed.** Only five channels were ingested. All 76 source archives were profiled read-only. The full profile is separate from model fitting/evaluation.

Reproduce the representative pilot:

```powershell
.\.venv\Scripts\python.exe -m app.cli profile --dataset '../data/esa_adb/mission1/ESA-Mission1' --output '../artifacts/profile'
.\.venv\Scripts\python.exe -m app.cli ingest --dataset '../data/esa_adb/mission1/ESA-Mission1' --channels 1 12 41 61 74 --output '../artifacts/telemetry'
.\.venv\Scripts\python.exe -m app.cli evaluate --dataset '../data/esa_adb/mission1/ESA-Mission1' --store '../artifacts/telemetry' --channels 1 12 41 61 74 --max-rows 20000 --batch-size 5000 --max-train-rows 10000 --unlabelled-policy assume_normal --output '../artifacts/pilot'
```

Repeat the identical ingestion/evaluation command to resume. Successful channels with matching source/configuration and verified artifact hashes are skipped. Failed/interrupted channels restart from their beginning; a pickle cannot be resumed from an arbitrary row. Ingestion supports `--force`. For changed analysis configuration or code, use a new output directory; completed experiment manifests are not silently repurposed.

Two additional bounded diagnostic windows exercise real positive annotations. These windows were deliberately selected using annotation dates, so their results are **diagnostic pilot results, not unbiased benchmark estimates**. Each uses 14,000 training rows followed by 6,000 test rows; no thresholds were tuned after inspecting test results.

```powershell
.\.venv\Scripts\python.exe -m app.cli evaluate --dataset '../data/esa_adb/mission1/ESA-Mission1' --store '../artifacts/telemetry' --channels 12 --start '2000-03-01T00:00:00Z' --max-rows 20000 --batch-size 5000 --max-train-rows 10000 --unlabelled-policy assume_normal --output '../artifacts/pilot_annotation_interval'
.\.venv\Scripts\python.exe -m app.cli evaluate --dataset '../data/esa_adb/mission1/ESA-Mission1' --store '../artifacts/telemetry' --channels 61 --start '2006-11-01T00:00:00Z' --max-rows 20000 --batch-size 5000 --max-train-rows 10000 --unlabelled-policy assume_normal --output '../artifacts/pilot_annotation_point'
```

## Repository structure and changed files

```text
backend/
  app/
    storage.py       # strict ZIP validation, profiling, Parquet, resume
    features.py      # causal duration windows and bounded streaming history
    detectors.py     # statistical, IF, experimental PCA and supervised RF
    events.py        # annotations, point tolerance, timestamp gaps, grouping
    evaluation.py    # streaming counts, one-to-one event matching, exposure
    experiment.py    # feature store, chronological runner and manifests
    artifacts.py     # atomic JSON, locks, hashes, RSS/runtime, JSON logging
    cli.py           # profile / ingest / evaluate
    ml.py            # existing names retained as safe compatibility wrappers
    pipeline.py      # existing database/API bridge to the new engine
    core.py          # additional optional settings
    telemetry.py     # strict legacy loading and annotation metadata validation
    main.py          # rollback before recording background failures
    db.py, rag.py    # unchanged
  tests/
    test_storage.py, test_temporal_features.py, test_detectors.py
    test_events.py, test_evaluation.py, test_experiment.py
    test_ml_compatibility.py, test_pipeline.py
    test_annotations.py, test_ml.py  # original tests retained
  requirements.txt
  .env.example
frontend/            # unchanged
data/esa_adb/         # unchanged original sources
artifacts/           # generated, ignored by Git
  profile/, telemetry/, pilot/
  pilot_annotation_interval/, pilot_annotation_point/, verification/
```

Added: the eight engine modules above (`storage`, `features`, `detectors`, `events`, `evaluation`, `experiment`, `artifacts`, `cli`), eight test files, and `docs/MILESTONE1.md`, `docs/DATASET_PROFILE.md`, `docs/PILOT_RESULTS.md`.

Modified: `backend/app/{core,telemetry,ml,pipeline,main}.py`, `backend/requirements.txt`, `backend/.env.example`, `.gitignore`, `README.md`, `docs/ARCHITECTURE.md`, `docs/IMPLEMENTATION_STATUS.md`. Existing `.env`, `db.py`, `rag.py`, frontend files and original tests were not modified.

## Scientific and storage contracts

- Source ZIP/pickle files are read only. One entire trusted pickle is the unavoidable ingestion memory floor. Numeric validation, Parquet conversion and subsequent processing are chunked. Invalid timestamps, duplicates, disorder, infinite values or ambiguous schemas fail explicitly instead of being silently removed. NaNs are preserved and reported separately from timestamp gaps.
- Source float32 values and UTC nanosecond timestamps are preserved. Parquet ingestion defaults to 250,000-row groups. Downstream reads default to 25,000 rows; model training defaults to at most 20,000 sampled rows and 100 trees on two CPU workers. GPU execution is unnecessary for this path.
- The full-profile cadence is a deterministic distributed sample of adjacent timestamp deltas. Analysis cadence is independently estimated from at most the first 10,000 **training** timestamps. It does not use future timing information. Actual prefix cadences match the supplied representative values; full-mission medians differ for several channels because sampling regimes change.
- Feature windows are durations `cadence × window_samples × scale` (default 30 observations and scales 1/4). Baselines use `[t-window,t)`, excluding the current observation. MAD is the exact median of absolute deviations around the window's median. An epsilon floor and explicit score cap handle zero MAD; constant signals stay finite, missing measurements do not become value-anomaly detections, and near-zero denominators produce unknown relative changes.
- Fit rows precede score rows. A seeded uniform priority reservoir limits model/calibration memory. Imputation, RobustScaler, IF contamination thresholds and optional statistical quantiles are fitted on training data only. A fixed statistical threshold of six MAD units is the default. Separate value and gap features/outputs retain their meaning.
- The held-out predictions artifact includes individual scores/flags and the OR ensemble. Ensemble scores are the maximum of each detector score divided by its own threshold. They are ranking evidence, not probabilities or physical severity. Individual detector events are retained for evaluation; the database publishes deduplicated combined events and timestamp-gap candidates only.
- Intervals match inclusively. Zero-duration annotations remain point events; default tolerance is half the training cadence, configurable down to zero. Annotation IDs and categories are retained. Event matches use maximum-cardinality **one-to-one** temporal overlap; one broad prediction cannot claim several truth events. Any nonempty interval overlap counts, not IoU or the ESA official affiliation/event metric. Per-channel records sharing an ESA ID are distinct annotation records.
- False alarms per day use adjacent observed elapsed time, excluding separations greater than the configurable gap threshold (default three cadences). No coverage is extrapolated beyond the first/last observed test timestamp. NaN values do not themselves create gap events. Timestamp gaps have no sample rows inside their missing interval, so gap evaluation is event-level and distinct from value-detector sample metrics.
- Sample category tasks compare each value category with other annotated value categories. Communication-gap-only samples are excluded from value sample metrics. Event category tasks compare predictions against that category's event records; under `assume_normal`, unmatched predictions are explicitly assumed false alarms. All three categories appear in reports.
- Annotation-only sample precision is conditional on available annotations, often with no known negative samples. Zero-division conventions and confusion matrices are explicit. Target=NO metrics are unavailable, rather than fabricated zero-performance claims. A positive annotation crossing the split can intersect the test horizon, but its labels never enter unsupervised training/calibration.

Arrow's batch/row-group APIs support bounded reads/writes ([Parquet documentation](https://arrow.apache.org/docs/python/parquet/parquet.html)). Training-only preprocessing follows scikit-learn's leakage guidance ([common pitfalls](https://scikit-learn.org/stable/common_pitfalls.html)). The project-specific temporal matching protocol above is deliberately documented separately from any official ESA leaderboard protocol.

## Experimental PCA and supervised RF

These are independent tested modules, not silently enabled in the standard univariate runner. Its manifest explicitly records why they were skipped.

`align_channels(channels, frequency, units, allow_mixed_units=False, max_rows=250000)` requires bounded timestamp-indexed inputs and explicit units. It uses causal mean bins `[t-frequency,t)` labelled at the right edge, no interpolation/backfill, and complete aligned rows only. Mixed units require explicit opt-in and are standardized with training-only robust location/scale. `PCAReconstructionDetector.fit(training, alignment=report, train_end=...)` learns reconstruction error and its threshold on training data, then scores held-out batches.

`fit_random_forest(training, labels, unlabelled_policy='exclude', labelled_channel=True, train_end=...)` accepts explicit 0/1/unknown labels, samples training rows deterministically and skips absent classes/insufficient ground truth. `app.ml.train_random_forest` provides chronological holdout evaluation. The optional `assume_normal` policy must be selected explicitly; Target=NO still never supplies negatives. Supply bounded experimental frames; these APIs do not load/align all 76 original channels. PCA/RF have not been benchmarked on the real dataset in this milestone.

## Phase validation and remaining limits

| Phase | Implementation and tests | Memory/code review and remaining limit |
|---|---|---|
| 1. Profile/ingestion | `storage.py`; 13 storage tests; 76/76 actual profiles | One pickle at a time; full profiling peak 559.77 MiB; source validity is strict |
| 2. Parquet feature store | Storage tests plus end-to-end/resume tests | Bounded Arrow row groups; atomic channel files; disk use grows with retained features |
| 3. Temporal features | Feature suite within 20 feature/detector tests | Exact MAD in bounded NumPy blocks; history cap rejects excessively dense windows |
| 4. Detectors | 20 feature/detector tests and compatibility tests | Capped CPU fitting and batched scoring; PCA/RF remain explicit experiments |
| 5. Timestamp gaps | Gap tests within 24 initial event/evaluation tests | Candidate gaps have no inferred communication cause; cadence changes need review |
| 6. Events/annotations | Interval, overlap, point, batching and deduplication tests | Grouping scans flagged runs; annotation matching is bounded by annotation count |
| 7. Evaluation | One-to-one matching and leakage tests | Labels/negative assumptions explicit; no official ESA benchmark equivalence claimed |
| 8. Experiments/API | 13 experiment tests; API/database and unlabelled-channel integration tests | Atomic checkpoints, artifact hashes and isolated transactions; resume is per channel |

Final integrated suite: **82 passed in 12.01 seconds**, with four deprecation warnings from the existing pandas day alias, Pydantic settings syntax and FastAPI/Starlette HTTPX integration. `pip check`: **no broken requirements**. Source preservation verification checked 778 file size/mtime records; `.env` and frontend SHA256 hashes were unchanged. The test database was temporary. No production database benchmark was performed and the unchanged frontend was not rebuilt or browser-tested.

The pilot establishes functioning engineering paths, not deployment-quality detector accuracy. The interval diagnostic produced many false positives and the point diagnostic missed its one truth event. Thresholds were not optimized against these held-out results. See `PILOT_RESULTS.md` for measured counts and resources.

Full 744.86-million-row feature generation and benchmark runtime remain unmeasured. Long-mission sampling regimes vary: a fixed training-derived time window can contain many more observations later. The configurable 10,000-row history cap fails clearly rather than allocating unbounded memory or silently shortening a window; a full run may require explicit window/history-budget choices. Exact MAD remains computationally expensive for dense long windows. Derived feature disk volume can exceed raw Parquet size; monitor free storage before the full benchmark.

Hashes verify derived artifacts and metadata; source ZIP identity uses size/mtime and ZIP-member CRC/size, not cryptographic hashing of every source archive. The original trusted pickle format can execute code when loaded; this engine intentionally handles the supplied local dataset, not arbitrary uploaded pickles. API background jobs are local-process tasks, not a distributed job queue. Use CLI manifests to resume interrupted analysis.
