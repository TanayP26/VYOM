# Event-level evaluation and ground-truth semantics

Official Mission 1 preparation initializes observations to nominal then overlays annotations, and explicitly states that training is not guaranteed normal. This supports nominal complement as a benchmark convention, not independently confirmed physical normality. [Official preparation code](https://raw.githubusercontent.com/kplabs-pl/ESA-ADB/main/notebooks/data-prep/Mission 1_semisupervised_prep_from_raw.py)

VYOM preserves original IDs and point/interval timestamps. Evaluation-only envelopes give point truth half the causally confirmed cadence at the preceding observation. Interval matching remains inclusive. Maximum-cardinality one-to-one matching prevents repeat credit. Reported F1 is VYOM's declared protocol, not ESA's official corrected event precision, alarming precision or affiliation score. [Official ESA metrics](https://raw.githubusercontent.com/kplabs-pl/ESA-ADB/main/timeeval/metrics/ESA_ADB_metrics.py)

Three views remain separate: annotation-supported recall with unknown negatives; label-independent event/sample burden; and precision/F1/false alarms under an explicit assumed-normal convention. Repeated events overlapping truth are reported separately from events outside any annotation. Target=NO supplies burden only, never supervised negatives.

False alarms/day use adjacent observed elapsed time excluding gaps larger than 3 contemporaneously expected cadences. No time is extrapolated beyond test endpoints. Point/interval value scoring is separate from resolved adaptive timestamp-gap candidates; a timestamp gap does not establish communication failure. Communication Gap labels are evaluated at event level, since the missing interval has no sample rows.

| Case | Model | Truth events | Matched | Unmatched | Missed | Duplicate overlaps | Outside any label | Events/day |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| prefix_channel_1/60_20_20 | robust_statistical | 0 | None | None | None | None | 1 | 0.2401 |
| prefix_channel_1/60_20_20 | isolation_forest | 0 | None | None | None | None | 0 | 0.0000 |
| prefix_channel_1/60_20_20 | temporal_point | 0 | None | None | None | None | 1 | 0.2401 |
| prefix_channel_1/60_20_20 | temporal_interval | 0 | None | None | None | None | 0 | 0.0000 |
| prefix_channel_1/60_20_20 | improved_temporal | 0 | None | None | None | None | 1 | 0.2401 |
| prefix_channel_1/60_20_20 | combined | 0 | None | None | None | None | 1 | 0.2401 |
| prefix_channel_1/50_20_30 | robust_statistical | 0 | None | None | None | None | 1 | 0.1600 |
| prefix_channel_1/50_20_30 | isolation_forest | 0 | None | None | None | None | 0 | 0.0000 |
| prefix_channel_1/50_20_30 | temporal_point | 0 | None | None | None | None | 1 | 0.1600 |
| prefix_channel_1/50_20_30 | temporal_interval | 0 | None | None | None | None | 0 | 0.0000 |
| prefix_channel_1/50_20_30 | improved_temporal | 0 | None | None | None | None | 1 | 0.1600 |
| prefix_channel_1/50_20_30 | combined | 0 | None | None | None | None | 1 | 0.1600 |
| prefix_channel_12/60_20_20 | robust_statistical | 0 | 0 | 554 | 0 | 0 | 554 | 132.9932 |
| prefix_channel_12/60_20_20 | isolation_forest | 0 | 0 | 29 | 0 | 0 | 29 | 6.9617 |
| prefix_channel_12/60_20_20 | temporal_point | 0 | 0 | 27 | 0 | 0 | 27 | 6.4816 |
| prefix_channel_12/60_20_20 | temporal_interval | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| prefix_channel_12/60_20_20 | improved_temporal | 0 | 0 | 27 | 0 | 0 | 27 | 6.4816 |
| prefix_channel_12/60_20_20 | combined | 0 | 0 | 29 | 0 | 0 | 29 | 6.9617 |
| prefix_channel_12/50_20_30 | robust_statistical | 0 | 0 | 799 | 0 | 0 | 799 | 127.8613 |
| prefix_channel_12/50_20_30 | isolation_forest | 0 | 0 | 79 | 0 | 0 | 79 | 12.6421 |
| prefix_channel_12/50_20_30 | temporal_point | 0 | 0 | 41 | 0 | 0 | 41 | 6.5611 |
| prefix_channel_12/50_20_30 | temporal_interval | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| prefix_channel_12/50_20_30 | improved_temporal | 0 | 0 | 41 | 0 | 0 | 41 | 6.5611 |
| prefix_channel_12/50_20_30 | combined | 0 | 0 | 81 | 0 | 0 | 81 | 12.9622 |
| prefix_channel_41/60_20_20 | robust_statistical | 0 | 0 | 33 | 0 | 0 | 33 | 24.9580 |
| prefix_channel_41/60_20_20 | isolation_forest | 0 | 0 | 32 | 0 | 0 | 32 | 24.2017 |
| prefix_channel_41/60_20_20 | temporal_point | 0 | 0 | 22 | 0 | 0 | 22 | 16.6387 |
| prefix_channel_41/60_20_20 | temporal_interval | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| prefix_channel_41/60_20_20 | improved_temporal | 0 | 0 | 22 | 0 | 0 | 22 | 16.6387 |
| prefix_channel_41/60_20_20 | combined | 0 | 0 | 41 | 0 | 0 | 41 | 31.0084 |
| prefix_channel_41/50_20_30 | robust_statistical | 0 | 0 | 50 | 0 | 0 | 50 | 25.2057 |
| prefix_channel_41/50_20_30 | isolation_forest | 0 | 0 | 67 | 0 | 0 | 67 | 33.7756 |
| prefix_channel_41/50_20_30 | temporal_point | 0 | 0 | 57 | 0 | 0 | 57 | 28.7345 |
| prefix_channel_41/50_20_30 | temporal_interval | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| prefix_channel_41/50_20_30 | improved_temporal | 0 | 0 | 57 | 0 | 0 | 57 | 28.7345 |
| prefix_channel_41/50_20_30 | combined | 0 | 0 | 87 | 0 | 0 | 87 | 43.8579 |
| prefix_channel_61/60_20_20 | robust_statistical | 0 | 0 | 14 | 0 | 0 | 14 | 0.3361 |
| prefix_channel_61/60_20_20 | isolation_forest | 0 | 0 | 14 | 0 | 0 | 14 | 0.3361 |
| prefix_channel_61/60_20_20 | temporal_point | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| prefix_channel_61/60_20_20 | temporal_interval | 0 | 0 | 1 | 0 | 0 | 1 | 0.0240 |
| prefix_channel_61/60_20_20 | improved_temporal | 0 | 0 | 1 | 0 | 0 | 1 | 0.0240 |
| prefix_channel_61/60_20_20 | combined | 0 | 0 | 1 | 0 | 0 | 1 | 0.0240 |
| prefix_channel_61/50_20_30 | robust_statistical | 0 | 0 | 21 | 0 | 0 | 21 | 0.3361 |
| prefix_channel_61/50_20_30 | isolation_forest | 0 | 0 | 21 | 0 | 0 | 21 | 0.3361 |
| prefix_channel_61/50_20_30 | temporal_point | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| prefix_channel_61/50_20_30 | temporal_interval | 0 | 0 | 1 | 0 | 0 | 1 | 0.0160 |
| prefix_channel_61/50_20_30 | improved_temporal | 0 | 0 | 1 | 0 | 0 | 1 | 0.0160 |
| prefix_channel_61/50_20_30 | combined | 0 | 0 | 1 | 0 | 0 | 1 | 0.0160 |
| prefix_channel_74/60_20_20 | robust_statistical | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| prefix_channel_74/60_20_20 | isolation_forest | 0 | 0 | 207 | 0 | 0 | 207 | 1490.7727 |
| prefix_channel_74/60_20_20 | temporal_point | 0 | 0 | 52 | 0 | 0 | 52 | 374.4936 |
| prefix_channel_74/60_20_20 | temporal_interval | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| prefix_channel_74/60_20_20 | improved_temporal | 0 | 0 | 52 | 0 | 0 | 52 | 374.4936 |
| prefix_channel_74/60_20_20 | combined | 0 | 0 | 184 | 0 | 0 | 184 | 1325.1313 |
| prefix_channel_74/50_20_30 | robust_statistical | 0 | 0 | 2 | 0 | 0 | 2 | 9.6016 |
| prefix_channel_74/50_20_30 | isolation_forest | 0 | 0 | 270 | 0 | 0 | 270 | 1296.2160 |
| prefix_channel_74/50_20_30 | temporal_point | 0 | 0 | 97 | 0 | 0 | 97 | 465.6776 |
| prefix_channel_74/50_20_30 | temporal_interval | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| prefix_channel_74/50_20_30 | improved_temporal | 0 | 0 | 97 | 0 | 0 | 97 | 465.6776 |
| prefix_channel_74/50_20_30 | combined | 0 | 0 | 262 | 0 | 0 | 262 | 1257.8096 |
| interval_channel_12/60_20_20 | robust_statistical | 1 | 1 | 475 | 0 | 31 | 444 | 86.5761 |
| interval_channel_12/60_20_20 | isolation_forest | 1 | 0 | 27 | 1 | 0 | 27 | 4.9108 |
| interval_channel_12/60_20_20 | temporal_point | 1 | 1 | 31 | 0 | 5 | 26 | 5.8202 |
| interval_channel_12/60_20_20 | temporal_interval | 1 | 1 | 3 | 0 | 3 | 0 | 0.7275 |
| interval_channel_12/60_20_20 | improved_temporal | 1 | 1 | 31 | 0 | 5 | 26 | 5.8202 |
| interval_channel_12/60_20_20 | combined | 1 | 1 | 31 | 0 | 5 | 26 | 5.8202 |
| interval_channel_12/50_20_30 | robust_statistical | 1 | 1 | 748 | 0 | 31 | 717 | 98.7946 |
| interval_channel_12/50_20_30 | isolation_forest | 1 | 0 | 36 | 1 | 0 | 36 | 4.7485 |
| interval_channel_12/50_20_30 | temporal_point | 1 | 1 | 42 | 0 | 5 | 37 | 5.6718 |
| interval_channel_12/50_20_30 | temporal_interval | 1 | 1 | 3 | 0 | 3 | 0 | 0.5276 |
| interval_channel_12/50_20_30 | improved_temporal | 1 | 1 | 42 | 0 | 5 | 37 | 5.6718 |
| interval_channel_12/50_20_30 | combined | 1 | 1 | 42 | 0 | 5 | 37 | 5.6718 |
| point_channel_61/60_20_20 | robust_statistical | 0 | 0 | 14 | 0 | 0 | 14 | 0.3362 |
| point_channel_61/60_20_20 | isolation_forest | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| point_channel_61/60_20_20 | temporal_point | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| point_channel_61/60_20_20 | temporal_interval | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| point_channel_61/60_20_20 | improved_temporal | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| point_channel_61/60_20_20 | combined | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| point_channel_61/50_20_30 | robust_statistical | 1 | 0 | 20 | 1 | 0 | 20 | 0.3202 |
| point_channel_61/50_20_30 | isolation_forest | 1 | 0 | 0 | 1 | 0 | 0 | 0.0000 |
| point_channel_61/50_20_30 | temporal_point | 1 | 1 | 1 | 0 | 0 | 1 | 0.0320 |
| point_channel_61/50_20_30 | temporal_interval | 1 | 0 | 0 | 1 | 0 | 0 | 0.0000 |
| point_channel_61/50_20_30 | improved_temporal | 1 | 1 | 1 | 0 | 0 | 1 | 0.0320 |
| point_channel_61/50_20_30 | combined | 1 | 1 | 1 | 0 | 0 | 1 | 0.0320 |
| pca_aligned_channel_41/60_20_20 | robust_statistical | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| pca_aligned_channel_41/60_20_20 | isolation_forest | 0 | 0 | 1 | 0 | 0 | 1 | 7.2180 |
| pca_aligned_channel_41/60_20_20 | temporal_point | 0 | 0 | 4 | 0 | 0 | 4 | 28.8722 |
| pca_aligned_channel_41/60_20_20 | temporal_interval | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| pca_aligned_channel_41/60_20_20 | improved_temporal | 0 | 0 | 4 | 0 | 0 | 4 | 28.8722 |
| pca_aligned_channel_41/60_20_20 | combined | 0 | 0 | 4 | 0 | 0 | 4 | 28.8722 |
| pca_aligned_channel_41/60_20_20 | pca_experimental | 0 | 0 | 4 | 0 | 0 | 4 | 28.8722 |
| pca_aligned_channel_74/60_20_20 | robust_statistical | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| pca_aligned_channel_74/60_20_20 | isolation_forest | 0 | 0 | 19 | 0 | 0 | 19 | 137.1429 |
| pca_aligned_channel_74/60_20_20 | temporal_point | 0 | 0 | 8 | 0 | 0 | 8 | 57.7444 |
| pca_aligned_channel_74/60_20_20 | temporal_interval | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| pca_aligned_channel_74/60_20_20 | improved_temporal | 0 | 0 | 8 | 0 | 0 | 8 | 57.7444 |
| pca_aligned_channel_74/60_20_20 | combined | 0 | 0 | 19 | 0 | 0 | 19 | 137.1429 |
| pca_aligned_channel_74/60_20_20 | pca_experimental | 0 | 0 | 4 | 0 | 0 | 4 | 28.8722 |
| pca_aligned_channel_41/50_20_30 | robust_statistical | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| pca_aligned_channel_41/50_20_30 | isolation_forest | 0 | 0 | 2 | 0 | 0 | 2 | 9.6160 |
| pca_aligned_channel_41/50_20_30 | temporal_point | 0 | 0 | 4 | 0 | 0 | 4 | 19.2321 |
| pca_aligned_channel_41/50_20_30 | temporal_interval | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| pca_aligned_channel_41/50_20_30 | improved_temporal | 0 | 0 | 4 | 0 | 0 | 4 | 19.2321 |
| pca_aligned_channel_41/50_20_30 | combined | 0 | 0 | 4 | 0 | 0 | 4 | 19.2321 |
| pca_aligned_channel_41/50_20_30 | pca_experimental | 0 | 0 | 5 | 0 | 0 | 5 | 24.0401 |
| pca_aligned_channel_74/50_20_30 | robust_statistical | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| pca_aligned_channel_74/50_20_30 | isolation_forest | 0 | 0 | 22 | 0 | 0 | 22 | 105.7763 |
| pca_aligned_channel_74/50_20_30 | temporal_point | 0 | 0 | 3 | 0 | 0 | 3 | 14.4240 |
| pca_aligned_channel_74/50_20_30 | temporal_interval | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 |
| pca_aligned_channel_74/50_20_30 | improved_temporal | 0 | 0 | 3 | 0 | 0 | 3 | 14.4240 |
| pca_aligned_channel_74/50_20_30 | combined | 0 | 0 | 22 | 0 | 0 | 22 | 105.7763 |
| pca_aligned_channel_74/50_20_30 | pca_experimental | 0 | 0 | 5 | 0 | 0 | 5 | 24.0401 |

## Category and point/interval evidence

Each case's `report.json` contains `per_category` results for Anomaly/Rare Event, `per_geometry` point/interval views, original and effective truth timestamps, matched IDs and prediction intervals. Communication Gap results are separate in `communication_gaps`. `events.jsonl` includes duration, peak score, peak time and annotation IDs. Scores retain model-specific units and are not probabilities.

| Case | Adaptive gap predictions | Communication Gap truth | Matched | Missed |
|---|---:|---:|---:|---:|
| prefix_channel_1/60_20_20 | 0 | 0 | None | None |
| prefix_channel_1/50_20_30 | 0 | 0 | None | None |
| prefix_channel_12/60_20_20 | 0 | 0 | 0 | 0 |
| prefix_channel_12/50_20_30 | 0 | 0 | 0 | 0 |
| prefix_channel_41/60_20_20 | 0 | 0 | 0 | 0 |
| prefix_channel_41/50_20_30 | 0 | 0 | 0 | 0 |
| prefix_channel_61/60_20_20 | 0 | 0 | 0 | 0 |
| prefix_channel_61/50_20_30 | 0 | 0 | 0 | 0 |
| prefix_channel_74/60_20_20 | 0 | 0 | 0 | 0 |
| prefix_channel_74/50_20_30 | 0 | 0 | 0 | 0 |
| interval_channel_12/60_20_20 | 0 | 0 | 0 | 0 |
| interval_channel_12/50_20_30 | 0 | 0 | 0 | 0 |
| point_channel_61/60_20_20 | 0 | 0 | 0 | 0 |
| point_channel_61/50_20_30 | 3 | 0 | 0 | 0 |
| pca_aligned_channel_41/60_20_20 | 0 | 0 | 0 | 0 |
| pca_aligned_channel_74/60_20_20 | 0 | 0 | 0 | 0 |
| pca_aligned_channel_41/50_20_30 | 0 | 0 | 0 | 0 |
| pca_aligned_channel_74/50_20_30 | 0 | 0 | 0 | 0 |

The positive-window interval-specific strategy still emits multiple fragments within one truth interval. Strict one-to-one precision penalizes these as unmatched predictions; the duplicate-overlap column distinguishes them from outside-annotation burden. No duplicate true positives are manufactured.

The old point miss was not a label tolerance error: its timestamp exactly exists. The repaired point strategy retains prior observations across the 16.7-hour gap and marks that reference stale. This can also alert on legitimate post-gap state changes; operator interpretation and broader validation remain necessary.

[Full comparison manifest](../artifacts/milestone11/comparison_final/manifest.json) · [Root-cause and primary-source investigation](M11_ROOT_CAUSES.md)
