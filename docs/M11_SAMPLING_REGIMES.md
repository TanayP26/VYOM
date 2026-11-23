# Sampling regime report

A sampling-only scan covered all 59,926,812 timestamps in the five existing Parquet channels. No full 76-channel anomaly benchmark was run. UTC source timestamps and M1 profile artifacts remain unchanged.

A persistent change requires 8 consecutive deltas within 5% of the first candidate delta and outside 5% of the current cadence. Cadence changes causally at confirmation; `effective_start` is retrospective descriptive metadata only. It is never used to rewrite past features or tolerances. Isolated deltas greater than 3 expected cadences remain gap candidates, with an unknown cause. Pending transitions are resolved on return/inconsistency; terminal pending intervals are explicitly unconfirmed.

| Channel | Rows | Confirmed segments | Distinct segment cadences | Resolved gap candidates | Seconds | Peak RSS MiB |
|---|---:|---:|---|---:|---:|---:|
| channel_1 | 10,513,336 | 471 | 3s, 90s, 450s, 900s | 334 | 7.035 | 138.70 |
| channel_12 | 14,258,506 | 90 | 0.375s, 3s, 90s, 180s, 360s | 153 | 2.198 | 152.97 |
| channel_41 | 15,381,169 | 33 | 3s, 30s, 600s | 8,214 | 35.840 | 148.02 |
| channel_61 | 487,448 | 1 | 900s | 13 | 0.039 | 128.88 |
| channel_74 | 19,286,353 | 6 | 3s, 6s, 30s | 459 | 1.292 | 151.08 |

Whole scan: **46.457 seconds**, sampled peak RSS **154.469 MiB**. The estimator stores at most one batch, pending confirmation observations and a capped segment list. Normal runs use vectorized updates; irregular portions require more work.

## Duration by confirmed cadence

| Channel | Cadence seconds | Total segment duration days |
|---|---:|---:|
| channel_1 | 3 | 198.391185 |
| channel_1 | 90 | 4884.015404 |
| channel_1 | 450 | 0.371667 |
| channel_1 | 900 | 31.221667 |
| channel_12 | 0.375 | 39.473308 |
| channel_12 | 3 | 12.611528 |
| channel_12 | 90 | 5025.417761 |
| channel_12 | 180 | 0.876042 |
| channel_12 | 360 | 35.621285 |
| channel_41 | 3 | 0.294861 |
| channel_41 | 30 | 5093.000461 |
| channel_41 | 600 | 20.704253 |
| channel_61 | 900 | 5113.993673 |
| channel_74 | 3 | 43.707691 |
| channel_74 | 6 | 302.956389 |
| channel_74 | 30 | 4767.335843 |

All 601 segment start/end times and durations: [detailed segment report](../artifacts/milestone11/reports/sampling_regime_details.md). Per-channel profile JSON and gap candidate JSONL are in [the sampling manifest](../artifacts/milestone11/regimes/sampling_regimes.json).

Expected sampling changes are not automatically communication failures. An 8-observation confirmation delay is deliberate; very short bursts, gradual cadence drift and periodic irregular schedules may remain uncertain deviations. Gap candidates at the end of a bounded window can be unresolved. These limits are retained in evidence instead of retrospectively changing causal scores.
