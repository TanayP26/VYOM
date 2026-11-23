# Milestone 1.2 — streaming benchmark design and evaluation protocol

Status: **design only; no full anomaly benchmark has been executed in M1.2**. Ingestion and integrity verification do not fit, calibrate or score detectors. This document specifies the separate runner required after the ingestion review. The bounded M1.1 comparison runner and all previous results remain intact.

The machine-readable [benchmark protocol](../artifacts/milestone12/benchmark_protocol.json) records the existing configuration, source hashes and exact development-exposure windows. Its `execution_authorized` and `benchmark_executed` fields are false. It is a protocol record, not an executable benchmark or a claim that the implementation below exists.

## Existing implementation and concrete blockers

Inspection covered `comparison.py`, `features.py`, `temporal.py`, `cadence.py`, `calibration.py`, `detectors.py`, `events.py`, `evaluation.py` and `scientific.py`, together with the seven M1/M1.1 documents requested for this milestone.

| Component | What can be reused | Required work for a full benchmark |
|---|---|---|
| `comparison._read_window`, `_score_in_batches`, `run_window` | Preserved diagnostic behavior and case manifests | They concatenate all raw rows, feature frames, cadence frames and predictions within a bounded window. Keep the 100,000-row safety limit; build a separate streaming orchestrator. |
| `calibration.split_manifest` | Chronological split formula and boundary semantics | Obtain row counts from verified ingestion metadata and retrieve boundary timestamps in bounded reads; do not construct a full index. |
| `TemporalDetector.fit` | Exact finite-value median, MAD and positive adjacent-step median; unchanged scale-floor rule | It currently builds full training arrays. Add exact disk-backed order statistics and multiple bounded passes, with parity tests before use. |
| `QuantileCalibrator.fit` | Fixed 1% upper-tail budget, minimum temporal threshold 3, `method="higher"`, strict exceedance | It currently collects all finite validation scores. External sorted runs/order-statistic selection must return the same threshold and exceedance count. |
| `TemporalFeatureBuilder` | Causal baseline features, fixed initial-cadence windows and 10,000-row history guard | Dense later regimes can exceed the frozen guard and raise. Do not silently increase the cap, truncate, resample or feed adaptive cadence into this legacy comparator. Record an explicit failed/unsupported comparator with coverage; exact disk-backed window evaluation is a separate compatibility proposal requiring review. |
| `SamplingRegimeTracker`, `TemporalDetector.score`, `DetectionPolicy`, `TemporalEventGrouper` | Bounded causal state across updates | Add versioned serialization and state validation. Drain completed gap/regime outputs to immutable fragments; retain pending hypotheses and open events. Preserve the configured regime limit and temporal-history truncation evidence. |
| `BoundedTrainingSampler`, IF fitting | Seeded priority sample; train-only imputation/scaling; bounded model fit | Persist the sampler RNG state, retained priorities/rows and chronological cursor. Preserve the exact input column order and float conversions. |
| `scientific.evaluate_detector` | Scientific interpretation and the existing metric definitions | It takes full arrays, builds correlated event lists and rescans category/geometry views. Replace orchestration with bounded counters and event-fragment iterators, preserving results. |
| `EventMetricAccumulator` | Maximum-cardinality one-to-one matching, bounded by truth count | Serialize its matching graph and counters; retain each original annotation row separately even when IDs repeat. |
| `align_channels` and PCA | Existing explicit pair, units, causal 30-second aggregation | Current alignment collects bounded frames. Preserve existing PCA diagnostics. A full paired PCA run requires a separate declared alignment plan and bounded bin state; it is not silently generalized to all channels. |

The original M1 `app.cli evaluate` command is not a substitute for this runner: it does not implement the M1.1 three-way calibration, adaptive timing and scientific reporting contract. No existing CLI or API contract is changed by this design.

## Freeze contract

There are two different forms of frozen state. Both must be identified in every future report.

1. **Existing fitted diagnostic artifacts:** every recorded threshold, scale, fitted model, configuration and prediction from M1/M1.1 stays byte-for-byte unchanged. A diagnostic replay uses its original fitted artifact or reproduces its original fitting procedure and checks parity in a new output directory. No existing artifact is recalibrated, replaced or selected because its test result looks better.
2. **A proposed full-channel fitting protocol:** 71 channels have no M1.1 fitted artifacts, and the five exposed channels have window-specific models rather than full-channel models. The existing numeric thresholds cannot be called full-channel fitted thresholds. A later benchmark must explicitly choose whether to permit new train/validation-only fits under the frozen M1.1 algorithm, or to specify a scientifically justified transfer mapping for existing fitted models. M1.2 does neither. The streaming stages below describe the first option as a proposal for the post-ingestion review, not an authorization to change learned parameters now.

For that proposed later protocol, freeze the algorithm, all hyperparameters, split rules, sampling seed, feature schema, numeric dtype conversions, dependency versions and code hashes before any B outcome is examined. Freeze each newly fitted per-channel model and calibrated threshold before its test partition is read for scoring. New fitted values would be explicitly named as such; they must never overwrite the diagnostic freeze or be described as unchanged M1.1 fitted values.

Preserved M1.1 settings include:

| Setting | Existing value/behavior |
|---|---|
| Primary split | 60% train, 20% validation, 20% test, by chronological observation count |
| Diagnostic secondary split | 50/20/30; preserves the original M1 6,000-row holdout |
| Statistical threshold | 6; strict greater-than comparison |
| IF | contamination 0.01; 100 trees; seed 42; at most 10,000 training rows; at most 256 samples per tree; two jobs |
| Temporal calibration | finite validation scores; upper quantile 0.99 using `higher`; minimum threshold 3; no labels |
| Temporal history | point reference 31; duration scales 8/120/480 cadences; retained history 4,096; block size 128; epsilon 1e-6; score cap 1e6 |
| Interval policy | three consecutive exceedances; release below half threshold |
| Cadence | 5% tolerance; eight-delta confirmation; gap factor 3; maximum 100,000 regimes |
| Event bridge | baseline 1.5 cadences; temporal 2 cadences |
| Combined flag | temporal point OR interval OR (IF flag AND temporal ratio above 0.5) |
| Point tolerance | half the confirmed local cadence at the observation strictly preceding the original point |

The protocol JSON copies the complete M1.1 comparison configuration and hashes all 18 per-case model configuration files. Defaults outside that dataclass are covered by the inspected source hashes and recorded model metadata. Batch size is an engineering setting, but changing it is allowed only after batch-parity verification. No approximate quantile, new detector or label-driven tuning is proposed.

## Two separately identified evaluation datasets

### A — development-exposed diagnostics

A contains **all observations used in fitting, calibration, scoring and inspection**, not only the final partitions:

- First 20,000 raw rows of channels 1, 12, 41, 61 and 74.
- The 20,000-row channel 12 interval window starting at the first observation on/after `2000-03-01T00:00:00Z`.
- The 20,000-row channel 61 point window starting at the first observation on/after `2006-11-01T00:00:00Z`.
- Both existing splits of those seven windows, plus both splits of the aligned channel 41/channel 74 PCA views. There are 18 recorded cases in total. The PCA view contains 2,000 common 30-second bins; its source observations are already inside the exposed raw prefixes. The right-edge bin timestamps are preserved separately from the contributing raw ranges.

Exact UTC endpoints, splits, configuration hashes and alignment metadata come from the preserved [M1.1 manifest](../artifacts/milestone11/comparison_final/manifest.json), copied into the protocol JSON. The M1 pilot manifests are also identified by SHA256. A is a regression/diagnostic dataset. In particular, the channel 61 point lies in validation under 60/20/20 and in the final partition under 50/20/30; do not shift boundaries to obtain positive test truth or pick the better split after scoring.

### B — retrospective held-out channels and chronological windows

B1 comprises the other 71 channels, whose telemetry-value diagnostic windows were not used for M1/M1.1 detector development. B2 comprises later chronological test windows in channels 1, 12, 41, 61 and 74 outside A. The proposed primary test window is each complete channel's final 20%, using verified row counts and the exact existing integer split formula. Training and validation are the preceding 60% and 20%. Rows remain in chronological order; there is no random split or annotation-driven window selection.

Before any future B fit, materialize a plan containing every channel's row offsets, six boundary timestamps, source/Parquet hashes, annotation-catalog identity, configuration identity and A-exposure intersection. The full test range must have an empty intersection with the union of A raw and aligned evaluation ranges. An overlap fails planning with `exposure_overlap_requires_plan`; it must not be removed silently after seeing predictions. This conservative rule avoids inventing disconnected test windows or double-counting an event across exclusions. Any future additional windows need an explicit prior plan. Training/validation overlap with A is disclosed per channel; it does not turn a later B test into external validation.

All 76 channels have already undergone source summary profiling, and the five existing channels have undergone full-time timestamp-regime inspection. Dataset metadata and the annotation catalog were already inspected. Therefore neither A nor B is **external blind validation**, and B is not claimed to be unseen in every informational sense. B is a retrospective held-out evaluation under a frozen, declared procedure. A and B results stay in separate tables and output namespaces; they are never pooled to advertise an unbiased score.

## Proposed bounded execution stages

Use one channel worker by default on the 16 GB machine. Start with the existing 5,000-row scoring batch; Arrow input batches can be sliced at split boundaries. The full dataset and full channels are never materialized in pandas. Use the existing CPU environment and dependencies, with no GPU dependency.

1. **Identity and planning.** Require a complete successful ingestion integrity report and verified hashes. Resolve row-count boundaries from the manifest, then read the few boundary timestamps. Check chronological uniqueness, A/B separation, frozen protocol/code/environment and disk/RAM budgets. Estimate each stage's work and temporary files before fitting; ingestion timing alone does not estimate rolling-feature or model throughput.
2. **Train statistics pass.** Consume only the training rows. Initial cadence uses the existing median of at most the first 10,000 adjacent training deltas. Write bounded sorted finite-value runs and positive adjacent-difference runs to disk. Carry the immediately preceding raw value between batches, including missingness; never manufacture a difference across a missing row. Recover the exact median, reread training rows for exact absolute deviations, and recover their median. Preserve even-count median arithmetic and float64 conversion used by `TemporalDetector.fit`. Compute the identical floor/global/change scales. No validation or test values enter these statistics.
3. **Train features and bounded model fit.** Rewind to row zero with fresh causal feature/cadence state; stream training features into the seeded IF priority sampler. Preserve the same valid-row filter, column ordering, sample, imputation and scaling. Persist RNG state and retained sample at checkpoints. Fit IF only on that bounded sample. The statistical threshold remains six. If a frozen history guard fails, record the affected comparator and exact coverage; do not quietly change its settings or claim complete comparative results.
4. **Prefix scoring and validation calibration.** With fixed training statistics, stream train then validation in chronology, preserving cadence/temporal state. Spool prefix temporal scores and validation finite scores into bounded fragments. Compute exact external order statistics: for `n` finite scores the `higher` quantile selects zero-based rank `ceil((n-1)*0.99)`, then applies the unchanged floor. Count strict exceedances in a bounded pass. Approximate sketches, sampled validation tails and histogram approximations are not equivalent substitutes.
5. **Warm policy and freeze fitted artifacts.** After thresholds are known, replay stored train+validation score fragments through `DetectionPolicy` exactly as M1.1 does. Keep the causal feature/cadence state at validation end. Store the resulting policy state, exact model artifacts, thresholds, training/validation provenance and hashes atomically before test scoring. The warmup has no labels and contributes no test events or metrics. No final partition participates in fitting, imputation, scaling or calibration.
6. **Test scoring and event production.** Stream test rows once. Emit compact per-batch prediction fragments, cadence evidence and final event fragments. Carry raw-history, policy, cadence and open-group state across every batch and checkpoint. Start fresh test event groupers while retaining warmed detector state, matching the existing runner's test-boundary behavior. Resolve gap hypotheses causally and record resolution time. Never flush an event, finalize cadence or reset persistence just because a batch/file ends.
7. **Evaluation and reduction.** In a separate bounded pass over predictions/cadence/events, attach annotation evidence and update sample/event accumulators, so labels have no route into the scoring state. A timing-only pass can compute each point annotation's local causal tolerance from its preceding observation without storing full cadence arrays. Resolve all relevant truth envelopes before maximum matching, avoiding late modification of the truth graph. Stream all event records to disk; retain only counters, per-truth matching state and an annotation table for one channel. Produce per-channel/category/geometry reports, then reduce counts across successful channels with explicit coverage and failed/skipped cases.

External median/quantile runs use bounded memory and exact values. Their disk usage and sort/merge passes must be measured in a future benchmark preflight; the full ingestion preflight does not reserve an unlimited prediction store. A global memory map alone is not a memory bound if a library operation copies it. Check resident memory and temporary run sizes, and prove bounded paths with tests.

## Causal state and sampling transitions

Every checkpoint needs a schema version and a state payload tied to the source, split, configuration and code hashes:

- Input file/row-group cursor and next absolute row ordinal; last processed timestamp; stage and pass number.
- Cadence's initial/current cadence, previous timestamp, pending confirmation deltas, current regime, regime count and gap counters. Eight compatible deltas confirm a new regime; earlier cadence outputs are never rewritten. Retrospective `effective_start` remains descriptive metadata only. Preserve the maximum-regime guard even if completed regimes are streamed to disk.
- Temporal raw tail of at most 4,096 observations, exact timestamps/dtypes and last timestamp; training statistics; stale point-reference age and truncated-history counters. Gaps do not erase the retained point reference.
- Legacy feature tail and last timestamp, using its unchanged fixed-cadence semantics and guard. Baseline features must not silently become adaptive features.
- IF model/scaler/fill values, selected columns, and sampler RNG/keys/rows when fitting is incomplete.
- Interval persistence count, active hysteresis state and last timestamp; thresholds remain immutable during test.
- Each candidate's open event (start/end, peak score/time, observation count, evidence), last timestamp and last flagged cadence. Retain a single open event across batch edges; preserve the existing local-cadence bridge rule.
- Sample confusion/burden counters, observation-time accumulator, annotation cursor, event counters and one-to-one matching graph. Preserve any finalized output fragment IDs.

Only actual channel-end calls `finish`/`flush`. A final unconfirmed timing hypothesis retains the existing `end_of_stream_unconfirmed` evidence; it is not promoted to a proven communication failure. Prefix gap outputs are excluded from final-test predictions; a gap is test-eligible only when its entire missing interval lies inside test bounds, matching current behavior. At the validation/test boundary, pending hypotheses remain state, even when their eventual resolved event is ineligible for test metrics.

`TemporalEventGrouper.update` needs an explicit compatibility adapter: the frozen
implementation can flush an open event at the last quiet observation of each
call. A later upward cadence change can make the next flagged observation close
enough under the bridge rule, so a split call can produce two events where one
whole-window call produces one. The new runner must retain the open event until
the next flagged observation or actual test end and reproduce whole-window
event geometry. Finalizing such an event can be delayed, while sample flags
remain causal. Prove parity across cadence transitions and restart; do not alter
the frozen diagnostic implementation or claim this adapter already exists.

## Resume and atomicity

Each channel has its own run directory and lock. A checkpoint generation records a contiguous processed row interval and all immutable output fragments that belong to it. For a batch: write new fragments/state to temporary files, close and flush them, calculate hashes, rename atomically on the same volume, then atomically replace the checkpoint pointer as the final commit. Input advancement, event emissions and metric updates are committed together. Never append directly to a published report.

Recovery verifies the protocol/source/model/checkpoint and fragment hashes before seeking the next row. Unreferenced files from an interrupted generation are not accepted as committed results. Restart from the preceding valid generation and deterministically replay the batch; stable fragment identities and the committed output list prevent duplicate rows/events. Do not deduplicate distinct scientific predictions just because their intervals happen to match. A completed channel is reusable only after all hashes, exact processed row coverage and final counters verify. Changed code, dependencies or protocol creates a new run identity, not a silent resume. A failed channel does not erase completed channels or prior diagnostics.

## Evaluation definitions and outputs

Keep value anomalies and timestamp-gap candidates separate. Value truth comprises Anomaly and Rare Event annotations, with point and interval geometries separately reported. Communication Gap truth is evaluated at event level only; no synthetic sample observations are inserted into a missing interval. Gap-only annotation coverage is excluded from value sample labels using the existing rule.

| View | Required output and interpretation |
|---|---|
| Annotation-supported sample recall | Detected annotated-positive rows / annotated-positive rows; precision/F1 unavailable without confirmed negatives. No positives means unavailable, not zero recall. |
| Annotation-supported event recall | Matched truth records / eligible truth records using maximum-cardinality one-to-one inclusive overlap. One prediction credits at most one truth record. No truth means unavailable. |
| Nominal-complement sample precision/F1 | Separate named assumption-dependent values on Target=YES only; retain TP/FP/FN/TN and excluded/unknown counts. |
| Nominal-complement event precision/F1 | Matched events / predicted events, plus one-to-one recall; unmatched predictions are assumed false alarms only in this view. This is VYOM overlap F1, not the official ESA corrected alarming/affiliation metric. |
| Redundant overlaps | Number of predictions overlapping relevant truth minus one-to-one matched predictions; distinct from events wholly outside truth. Preserve the corresponding annotation IDs and match assignments. |
| Outside-annotation burden | Count against all annotations, and separately against the task/category/geometry truth subset. The existing per-view `events_outside_any_label` actually uses that view's relevant truth; retain compatibility and add explicit scope to avoid implying a value event overlapping a gap was outside every source annotation. |
| False alarms/day | Assumed false events times 86,400 / observed exposure seconds, on labelled channels only. Also report label-independent total events/day. |
| Target=NO | Unknown labels; report predictions, timing and burden only. Never convert these channels into supervised normal examples or use them to train RF negative classes. |

Observed exposure sums positive adjacent deltas no greater than three times the contemporaneously expected **previous** cadence. Ignore only the first delta of a test partition, not the first delta of every batch. Do not extrapolate beyond test endpoints. Report elapsed wall-calendar duration separately. Causal transition latency can omit some elapsed time while a slower cadence is pending; keep that limitation visible.

Point envelopes use the confirmed cadence at the observation strictly before each original point. Preserve `OriginalStartTime`, `OriginalEndTime`, original ID and row identity, and `PointToleranceSeconds`; do not rewrite source annotations or substitute a channel-wide cadence. Interval bounds stay inclusive. Report boundary-censored truth/events and the eligibility rule. Per-category and per-geometry views are separate views of the same predictions, not disjoint event counts to add together.

Per-channel results must include all six existing univariate candidates, coverage, failures/abstentions, sample/interval/gap counts, calibration provenance, truncation and stale-reference evidence, one-to-one assignments, redundant overlaps, outside-annotation counts and the three interpretation views. A whole-channel comparator failure remains a failure and is excluded from that comparator's aggregate denominator; never omit it from coverage. RF remains skipped without valid supervised labels. PCA remains the existing separately identified diagnostic until a full paired plan is declared.

Global reports include micro counts and separately labelled macro summaries with eligible-channel counts; do not average undefined recall into zero or merge A/B, point/interval/gap tasks, or differing coverage. Persist compact machine-readable JSON summaries and partitioned prediction/event Parquet or JSONL fragments. Event records keep duration, peak score/time, original annotation IDs/categories and score semantics.

Record wall time by read/statistics/feature/fit/calibration/score/evaluation/write stage, channel total, CPU time, sampled peak process RSS, monitor interval, bytes read/written, peak temporary bytes and fragment size. Distinguish reused/shared feature time from independently measured detector runtime. RSS includes native allocations; sampled peaks can miss short spikes. Do not extrapolate full benchmark time from the 34.197-second bounded comparison as if all channels had identical cadence, density or event burden.

## Required implementation and acceptance work after review

This milestone adds this design and the protocol record only for benchmarking. A later implementation would add a separate runner/CLI entry point, exact disk-backed statistics/calibration adapters, versioned causal state serialization, transactional per-channel fragment/checkpoint storage, a streaming scientific evaluator and a report reducer. Existing diagnostic behavior, API contracts, frontend and database remain untouched.

Before any full benchmark, verify finite/missing/even-count statistics and quantile ties against existing exact implementations; compare scores, flags, grouping and metrics under multiple batch sizes; inject interruption after fragment/state/checkpoint writes; exercise pending cadence changes, long gaps, open events and hysteresis across restart; verify validation/test boundaries and Target=NO behavior; test duplicate/overlapping truths and undefined metrics; and measure memory on a long synthetic stream without accumulating output lists. A parity run may reproduce exposed diagnostics into a new directory; it must not tune their parameters.

Post-ingestion review still needs to resolve fitted-artifact transfer versus frozen-procedure fitting, the legacy dense-history compatibility limitation, event-grouping batch parity, and the future benchmark resource budget. Until then the operational stop remains: **finish all-channel ingestion, verify integrity, report resources and risks, and stop without running the anomaly benchmark.**
