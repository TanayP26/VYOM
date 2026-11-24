# M1.3.1 — Temporal-first operator incident policy

## Decision

M1.3.1 changes only the operator-facing incident decision policy. The active
combined stream is now the calibrated temporal detector's union:

~~~text
combined_flag = temporal_point_flag OR persistent_temporal_interval_flag
~~~

Isolation Forest remains a separately reported unsupervised comparator. Its
score and flag remain available for investigation and ranking, but IF cannot
create an operator-facing incident without a temporal detection.

The point/interval thresholds, 99th-percentile validation calibration,
persistence, release hysteresis, cadence tracker, feature definitions, event
grouping, and chronological 60/20/20 split are unchanged.

## Why this is the selected policy

The M1.1 development-exposed A diagnostics provide a defensible basis for
choosing a conservative operator policy:

- On the channel 12 interval diagnostic, improved temporal achieved sample
  F1 0.8711 and sample recall 0.9954. The IF comparator had zero sample recall
  and produced 36 events on the 50/20/30 holdout.
- On the channel 61 point diagnostic, improved temporal achieved sample F1
  0.6667 and recall 1.0; IF did not add a supported positive detection.
- On the channel 74 50/20/30 prefix diagnostic, the combined candidate emitted
  262 events versus 97 for improved temporal. This is a clear alert-burden
  increase, not evidence that IF should create operator incidents.

These are development-exposed, selection-biased A diagnostics. They support
the policy choice for the next experiment; they do not establish general
performance across Mission 1.

## What Run #10 B established — diagnosis only

Run #10 B was already exposed before M1.3.1. Its persisted sample-level
attribution was used to identify the failure mechanism, not to select or tune
the new policy:

| Quantity | Samples |
|---|---:|
| Test observations | 2,851,702 |
| Isolation Forest flags | 33,234 |
| Temporal flags | 12,919 |
| M1.3.0 combined flags | 38,465 |
| Combined and IF | 31,852 |
| Combined and temporal | 12,919 |
| IF + ratio > 0.5 without a temporal flag | 25,546 |
| Combined without IF or temporal support | 0 |
| Exact M1.3.0 Boolean-rule mismatches | 0 |

The 25,546 half-threshold-only samples explain why the old corroboration gate
admitted almost every IF candidate. No threshold was selected from the B
quantiles or gate-count table.

## Preserved comparison policies

The streaming runner now emits three clearly named policy candidates:

| Candidate | Rule | Status |
|---|---|---|
| combined | temporal_flag | **Active operator policy** |
| combined_m13_baseline | temporal_flag OR (IF_flag AND ratio > 0.5) | Frozen M1.3.0 comparator |
| combined_if_full_threshold | temporal_flag OR (IF_flag AND ratio > 1.0) | Research challenger only |

The full-threshold challenger has a semantic interpretation (the normalized
temporal score exceeds its calibrated threshold), but it is not activated and
must not be selected using Run #10 B. The original M1.3.0 rule remains
reproducible under its own candidate name.

## Validation and operating boundary

- New run identities include the operator-policy hash; M1.3.0 checkpoints
  cannot be resumed under M1.3.1.
- Every report records the active policy, preserved baseline and challenger.
- IF comparator failure does not disable the temporal-first operator stream.
- The product API's combined incident projection uses the temporal-first
  policy; IF remains separately visible as comparator evidence.
- Run #10 artifacts are immutable and remain the M1.3.0 baseline.

The next evaluation must use a predeclared, previously unexposed B1
Target=YES channel. Freeze this policy before looking at that channel's
labels or predictions. Do not run all 76 channels until the single-channel
evaluation, event burden, resource use and integrity checks have been reviewed.

This remains retrospective research decision support. It is not external blind
validation, a flight-qualified detector, or a claim of operational readiness.
