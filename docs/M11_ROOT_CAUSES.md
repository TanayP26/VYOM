# Milestone 1.1 — investigation before model changes

The preserved Milestone 1 artifacts were inspected read-only. No model was fitted and no threshold was changed for this investigation. Reproducible script: `backend/scripts/investigate_m11.py`; measured evidence: `artifacts/milestone11/investigation/baseline_forensics.json`. The diagnostic script took 0.301 seconds with a sampled peak process RSS of 210.598 MiB. Original artifact hashes are recorded in the evidence JSON.

## Channel 12: scale-floor mismatch and fragmented events

The mathematical MAD implementation is exact and causal; there is no rolling-residual approximation bug. The problem is its handling of a zero robust scale in a quantized, often constant signal.

| Observation | Measured value |
|---|---:|
| Distinct training values | 13 |
| Training rows with MAD = 0 | 89.657% |
| Test rows with MAD = 0 | 5,164 / 6,000 |
| Statistical flags with MAD = 0 | 1,806 / 1,818 |
| Unannotated flagged samples with MAD = 0 | 1,743 / 1,753 |
| Median absolute deviation of zero-MAD flagged samples | 0.001559883 |
| Median corresponding robust score | 1,559.883 |
| Fixed statistical threshold | 6 |

The same roughly 0.00156 change is the median nonzero change in training. With a denominator floor of `1e-6 × max(1, abs(median))`, an ordinary quantized step becomes a score around 1,560. The fixed threshold is therefore incompatible with the training signal's scale. The training score distribution itself already exposes the failure: its 75th percentile is 1,559.883. Calibration is absent, rather than a test-only distribution shift being the principal cause.

Isolation Forest produced 49 flagged samples, all already flagged by the statistical detector. It added **zero unique alerts** in this diagnostic. The OR ensemble's output equals the statistical output exactly. IF does not explain the observed alert excess, although an OR ensemble can increase alerts in other datasets.

The statistical detector uses only the short-window score. Of 431 positive samples, 366 have a score at or below six; 100 equal their current rolling median, showing adaptation to the anomalous interval. Twenty-nine missed positive samples have an unused longer-scale score above six. That observation motivates testing sustained, multiscale change features; it does not justify choosing a threshold using these test labels.

Event grouping closes an event on every negative sample. The 1,818 flagged samples become 783 events; 490 are single-sample events. Sixty-five predictions overlap the same ground-truth interval. Strict one-to-one evaluation credits only one, leaving **64 redundant overlapping alerts plus 718 predictions wholly outside the truth interval**. Milestone 1's 782 unmatched-event count combines these two kinds of burden. Neither widening overlap matching nor allowing duplicate true positives would fix the detector.

## Channel 61: the real point exists, but short-history gating suppresses it

The annotation `id_116` occurs exactly at an observed timestamp, `2007-04-15T00:41:23.373Z`. There is no rounding or tolerance miss.

| Field at the annotated observation | Measured value |
|---|---:|
| Previous observed value | 0.982790 |
| Annotated value | 0.508518 |
| First difference | -0.474272 |
| Time since previous observation | 60,065.511 seconds |
| Gap relative to expected 900-second cadence | 66.739 |
| Short-window history count | 0 |
| `feature_valid` | 0 |
| Short robust score stored by baseline | 0 |
| Long-scale robust score | 474,272.25 |

The 30-cadence baseline covers 7.5 hours. The preceding gap is approximately 16.7 hours, so that baseline contains no observations. Missing short-window statistics are converted to a zero score, and both statistical and IF scoring reject the row because `feature_valid` is zero. The 120-cadence, 30-hour feature still has historical context and a very large deviation, but neither baseline detector consumes it. This is an observable spike suppressed by a history-availability rule, not a failure of point annotation handling.

All 20 other combined events in this diagnostic contain exactly 15 samples. Their deviations are only 0.000152–0.002836 and their MAD is zero. The fixed 30-observation median takes about half a window to adapt to each small step, explaining the repeated 15-sample alert episodes. A point fallback should retain bounded prior observations and expose their age; it must not silently equate a post-gap comparison with a fresh local baseline.

Both `id_116` and `id_167` have source type metadata `Multivariate / Global / Subsequence`. The zero-duration channel-61 row remains a point annotation for that channel; the event's broader multichannel classification does not override its exact local interval.

## Ground-truth semantics checked against primary sources

The official Mission 1 preparation script initializes observation labels to nominal, then overlays category annotations. Thus treating other periods as nominal is an explicit **benchmark convention** supported by implementation, rather than a proof of physical normality. It also sets `train_is_normal = False`; the chronological training period is not guaranteed anomaly-free. [Official preparation code](https://raw.githubusercontent.com/kplabs-pl/ESA-ADB/main/notebooks/data-prep/Mission1_semisupervised_prep_from_raw.py)

The paper describes repeated expert/algorithm-assisted review of the whole signal, but acknowledges that “some mislabelling is inevitable”. It excludes unannotated non-target channels from assessment. This supports using Target=NO as contextual input, never as a negative class. The paper also identifies expected sampling-rate changes that were deliberately left unannotated, and warns that event end times are less certain than starts. Its original protocol uses chronological mission halves, reserving the last three training months for validation; anomalies occur in every partition. These are reasons to report both labelled-event recall and operational alert burden, with assumption-labelled false alarms, rather than claim exhaustive error-free ground truth. [ESA-ADB paper, Methods, discussion and Supplementary Material 2.2](https://arxiv.org/pdf/2406.17826)

The official metrics group truth fragments by original event ID, distinguish redundant detections through alarming precision, correct event precision using nominal-time specificity, and calculate affiliation measures. Their code counts outside-truth false positives separately from repeated detections within a true event. VYOM's maximum-cardinality one-to-one overlap metric is deliberately stricter in a different way and must not be called the official ESA leaderboard score. The benchmark normally reports beta=0.5; VYOM's current reports use F1. [Official metric implementation](https://raw.githubusercontent.com/kplabs-pl/ESA-ADB/main/timeeval/metrics/ESA_ADB_metrics.py), [official Mission 1 experiment configuration](https://raw.githubusercontent.com/kplabs-pl/ESA-ADB/main/mission1_experiments.py)

The official repository also states that its current algorithms treat rare nominal events as anomalies, although operators may view those expected activities differently. Preserve their category and report it separately. [Official benchmark README](https://github.com/kplabs-pl/ESA-ADB)

## Implications for the next experiments

- Learn numerical/quantization scale floors from training data and calibrate alert thresholds on chronological validation, rather than raising a constant until old test metrics look good.
- Use separate short-lived and persistent-change scores; test longer-scale evidence and causal post-gap history with explicit staleness.
- Merge nearby alert runs using parameters chosen before final testing, while retaining original sample predictions and distinguishing duplicate alerts from outside-truth alerts.
- Estimate sampling regimes independently of annotation labels. An isolated long interval is a gap candidate, not proof of a communication failure or a new stable cadence.
- Keep one-to-one matching, point tolerance and IDs intact. Report annotation-supported recall, total alerts, duplicate alerts and normality-assumption-based false alarms separately.
- These diagnostic windows and their labels have already been inspected in Milestone 1 and in this investigation. Subsequent final partitions can remain untouched by fitting/calibration code, but they are not a new externally unseen benchmark. Selection bias and prior exposure must remain disclosed.
