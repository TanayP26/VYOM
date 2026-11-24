# Scientific protocol

## Split discipline

Each channel is processed chronologically by observation count: 60% training, 20% validation/calibration, and 20% final retrospective evaluation. No random row shuffling. Final-partition labels are not used to fit statistics or thresholds.

M1.1 development diagnostics exposed five channels (1, 12, 41, 61 and 74). B1 comprises the other channels; B2 comprises later partitions of exposed channels. These are retrospective partitions, not an external blind experiment. The first B1 evaluation selected channel_13 before outcomes were inspected.

## Training statistics and calibration

The finite-value median, MAD and median positive adjacent step are computed using exact disk-backed order statistics. The quantization-aware denominator floor is:

`max(0.5 × median positive step, 0.1 × robust sigma, epsilon × level)`

Temporal point and interval thresholds use the exact 99th percentile of validation scores with the higher order statistic and a minimum threshold of 3. No labels are used in calibration.

## Candidate detectors

- Robust statistical: independent baseline.
- Temporal point: abrupt change relative to training-derived scale.
- Temporal interval: persistent deviation with hysteresis.
- Improved temporal: point or persistent interval evidence.
- Isolation Forest: independent deterministic bounded unsupervised comparator.
- Combined M1.3.1: temporal point OR persistent temporal interval. IF cannot independently create an operator incident.
- Timestamp gaps: cadence-relative missing-time candidates, not proof of communication failure.

M1.3.0 used temporal_flag OR (isolation_forest_flag AND temporal_ratio > 0.5). This historical rule applies to Run #10, not the current operator policy. See MILESTONE1_3_1_OPERATOR_POLICY.md.

## Event and metric semantics

Candidate samples are grouped causally across batches. Event records retain start/end, peak time, score, detector, channel and annotation overlap where available. Scores are not probabilities; display severity is not validated spacecraft consequence.

The event metric is one-to-one closed-interval overlap, not ESA's official corrected alarming precision or affiliation metric. Unmatched predictions have unknown physical truth. Nominal-complement precision and F1 are assumption-dependent; supported precision/F1 are unavailable without independently confirmed negative observations. Target=NO remains contextual/unlabelled, never a supervised negative class.

## Validation status

All 76 channels were ingested and verified. Run #10 (CH-12, M1.3.0) detected 1/1 annotated event with 31,308 combined candidates. Run #11 (CH-13, M1.3.1) detected 0/1 with 7,747 combined candidates. These are different channels; the shared annotation id_180 also prevents a claim of physical-event independence. The latest result does not establish improved detection quality.

Run #11 completed all six comparator streams on 2,851,702 test observations. See MILESTONE1_3_1_B1_EVALUATION.md for the full interpretation. Preserve both runs. Any future quality study requires a new frozen method and fresh evaluation. Full 76-channel modeling and external/flight validation have not been performed.
