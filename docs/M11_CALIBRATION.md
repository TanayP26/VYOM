# Threshold calibration report

No final-test labels were used to select thresholds, detector parameters, window lengths or event grouping. Candidate design followed the requested forensic investigation of previously exposed M1 diagnostics; consequently this is not an externally blind validation.

Training learns a robust value scale and the median nonzero adjacent step. The new local denominator floor is `max(0.5 × training step, 0.1 × training robust sigma, epsilon × level)`. This prevents a quantized ordinary step from being divided by a machine-scale epsilon. It is not a threshold chosen to improve a test metric.

Point and interval scores are calibrated independently at the predeclared 99th percentile of chronological validation scores, using the higher order statistic, with a minimum threshold of3. These are different score definitions and units from M1's fixed six-MAD threshold. Validation labels are not inputs; validation may contain anomalies. A 1% empirical score-tail budget is not a guaranteed physical false-alarm probability.

Interval activation requires 3 consecutive exceedances and releases below half its threshold. Point detections remain immediate. Temporal event merging bridges at most 2 local cadences; baselines use 1.5. These defaults were declared before new final scoring and were not searched against final metrics. The combined candidate adds IF only with half-threshold temporal corroboration.

| Case | Learned scale floor | Training positive-step median | Point threshold | Interval threshold | Point validation exceedance | Interval validation exceedance |
|---|---:|---:|---:|---:|---:|---:|
| prefix_channel_1/60_20_20 | 1e-06 | 0 | 3 | 3 | 0.00075 | 0 |
| prefix_channel_1/50_20_30 | 1e-06 | 0 | 3 | 3 | 0.00075 | 0 |
| prefix_channel_12/60_20_20 | 0.00077994168 | 0.0015598834 | 17.9977 | 3 | 0.00825 | 0 |
| prefix_channel_12/50_20_30 | 0.00077994168 | 0.0015598834 | 17.9977 | 3 | 0.009 | 0 |
| prefix_channel_41/60_20_20 | 0.00078517199 | 0.001570344 | 8.9967 | 3 | 0.00625 | 0 |
| prefix_channel_41/50_20_30 | 0.00078517199 | 0.001570344 | 8.49757 | 3 | 0.00875 | 0 |
| prefix_channel_61/60_20_20 | 0.0068807756 | 0.0045807511 | 3 | 3.20846 | 0 | 0 |
| prefix_channel_61/50_20_30 | 0.0049368751 | 0.0041080192 | 3 | 3.71983 | 0 | 0 |
| prefix_channel_74/60_20_20 | 0.002961129 | 0.0059222579 | 3.38375 | 3 | 0.00975 | 0 |
| prefix_channel_74/50_20_30 | 0.002961129 | 0.0059222579 | 3.23836 | 3 | 0.00975 | 0 |
| interval_channel_12/60_20_20 | 0.00077994168 | 0.0015598834 | 17.9977 | 3 | 0.004 | 0 |
| interval_channel_12/50_20_30 | 0.00077994168 | 0.0015598834 | 17.9977 | 3 | 0.0065 | 0 |
| point_channel_61/60_20_20 | 0.0091339073 | 0.0061820447 | 3 | 3 | 0.0005 | 0.00025 |
| point_channel_61/50_20_30 | 0.0082240072 | 0.0065249205 | 3 | 3 | 0 | 0 |
| pca_aligned_channel_41/60_20_20 | 0.00078451633 | 0.0015690327 | 5.00211 | 3 | 0.0075 | 0 |
| pca_aligned_channel_74/60_20_20 | 0.00045502186 | 0.00091004372 | 3.55535 | 3 | 0.0075 | 0 |
| pca_aligned_channel_41/50_20_30 | 0.00078451633 | 0.0015690327 | 5.25275 | 3 | 0.0075 | 0 |
| pca_aligned_channel_74/50_20_30 | 0.00045525134 | 0.00091050267 | 4.04921 | 3 | 0.0075 | 0 |

The statistical baseline retains threshold 6. IF retains contamination 0.01, deterministic seed 42, 100 trees, at most 10,000 training samples and two CPU workers. Temporal history is capped at 4096 observations; truncation is explicitly flagged. Its time windows are 8/120/480 confirmed cadences, and its point reference retains the previous 31 observations across a gap while exposing their age.

PCA is calibrated on its validation reconstruction-error tail after training-only robust scaling and PCA fitting. Every case persists `model_configuration.json` **before** final scoring, plus `validation_scores.parquet`, `threshold_calibration.json`, model artifacts and a frozen-configuration SHA256. Test mutations cannot change the stored model parameters or calibration, as verified by tests.

[Model configuration manifest and case artifact hashes](../artifacts/milestone11/comparison_final/manifest.json). Exact chronological boundaries and threshold evidence appear in each case's report/configuration files. Both split designs are retained, including the primary point-window case with zero positive events in its final partition.
