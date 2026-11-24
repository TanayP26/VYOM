# Scientific protocol

## Split discipline

Each channel is processed chronologically by observation count:

- 60% training
- 20% validation/calibration
- 20% final retrospective evaluation

Rows are never randomly shuffled. Final-partition labels are not used to fit training statistics or validation thresholds.

## Training statistics

VYOM computes the finite-value median, median absolute deviation and median positive adjacent step using an exact disk-backed SQLite order-statistic store. The local denominator floor is:

`max(0.5 × median positive step, 0.1 × robust sigma, epsilon × level)`

This prevents ordinary quantized telemetry steps from being divided by a machine-scale epsilon.

## Candidate detectors

- Temporal point score: abrupt change relative to training-only change scale.
- Temporal interval score: deviation relative to training-only robust scale.
- Isolation Forest: bounded deterministic training sample; unsupervised comparator.
- Combined: temporal evidence plus IF only when temporally corroborated.
- Timestamp gaps: cadence-relative missing-time candidates; they do not establish communication failure.

## Calibration

Point and interval thresholds use the exact 99th percentile of validation scores with the `higher` order statistic and minimum threshold 3. Labels are not used for threshold selection.

## Event semantics

Detection samples are grouped causally across processing batches. Event records retain start/end, peak time, peak score, detector, channel, annotation IDs and categories where overlap exists.

## Ground truth caveat

Unannotated observations can be treated as nominal for benchmark-style precision/F1 only as an explicit convention. This is not proof that those observations are physically error-free. `Target=NO` is not a negative class.

## Metric caveat

VYOM's event metric is one-to-one closed-interval overlap. It must not be presented as the official ESA corrected alarming precision or affiliation score.

## Validation status

The source repository completed all-channel ingestion/integrity and bounded detector diagnostics before this product consolidation. A full 76-channel benchmark should be rerun locally with this final distribution before quoting final product metrics.
