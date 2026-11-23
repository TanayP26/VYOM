# ESA Mission 1 dataset profile

Read-only scan completed on 22 November 2026 for all 76 original channel ZIP archives. This is a source profile, not a full ingestion or benchmark analysis.

- Observations: **744,856,895**.
- Compressed channel archives: **3,767,883,838 bytes** (3.51 GiB).
- Uncompressed pickle payloads: **8,938,358,731 bytes** (8.32 GiB).
- Target=YES: 58; Target=NO: 18.
- All channel value columns: float32. Missing values: 0. Invalid timestamps, duplicate timestamps, disorder, infinities and nonnumeric telemetry: none found.
- Annotation records: 3,589; type definitions: 200; unmatched IDs: 0; invalid intervals: 0; point annotations: 186.
- Categories: Rare Event 2,178; Anomaly 1,203; Communication Gap 208. All annotations map to Target=YES channels.
- Measured scan wall time: **40.182 s**; sampled peak process RSS: **559.766 MiB** (50 ms sampling).

Machine-readable details, schemas, missing percentages, min/max values, source identities and per-channel runtime: [dataset_profile.json](../artifacts/profile/dataset_profile.json).

Cadence below is the median of a bounded, evenly distributed sample of adjacent timestamp deltas over the full mission. P10/P90 are also sampled delta statistics. They are not a claim of constant sampling. The actual analysis training prefixes independently recovered the supplied representative intervals: channel 1 = 90 s, 12 = 90 s, 41 = 30 s, 61 = 900 s, 74 = 3 s. In contrast, full-mission medians for 1/12/74 are 3/0.375/30 s. Both observations are retained; values were not changed to fit the supplied examples.

| Channel | Target | Rows | Full-mission sampled median (s) | Sampled P10 (s) | Sampled P90 (s) | Missing values |
|---|---|---:|---:|---:|---:|---:|
| channel_1 | NO | 10,513,336 | 3 | 3 | 90 | 0 |
| channel_2 | NO | 10,513,336 | 3 | 3 | 90 | 0 |
| channel_3 | NO | 10,513,336 | 3 | 3 | 90 | 0 |
| channel_4 | NO | 3,589,376 | 167.25 | 0.75 | 180 | 0 |
| channel_5 | NO | 3,589,376 | 167.25 | 0.75 | 180 | 0 |
| channel_6 | NO | 3,589,376 | 167.25 | 0.75 | 180 | 0 |
| channel_7 | NO | 3,589,376 | 167.25 | 0.75 | 180 | 0 |
| channel_8 | NO | 3,589,376 | 167.25 | 0.75 | 180 | 0 |
| channel_9 | NO | 3,589,376 | 167.25 | 0.75 | 180 | 0 |
| channel_10 | NO | 3,589,376 | 167.25 | 0.75 | 180 | 0 |
| channel_11 | NO | 3,589,376 | 167.25 | 0.75 | 180 | 0 |
| channel_12 | YES | 14,258,506 | 0.375 | 0.375 | 90 | 0 |
| channel_13 | YES | 14,258,506 | 0.375 | 0.375 | 90 | 0 |
| channel_14 | YES | 5,272,893 | 90 | 90 | 90 | 0 |
| channel_15 | YES | 5,272,893 | 90 | 90 | 90 | 0 |
| channel_16 | YES | 5,272,893 | 90 | 90 | 90 | 0 |
| channel_17 | YES | 14,258,506 | 0.375 | 0.375 | 90 | 0 |
| channel_18 | YES | 14,258,506 | 0.375 | 0.375 | 90 | 0 |
| channel_19 | YES | 14,258,506 | 0.375 | 0.375 | 90 | 0 |
| channel_20 | YES | 14,258,506 | 0.375 | 0.375 | 90 | 0 |
| channel_21 | YES | 5,272,893 | 90 | 90 | 90 | 0 |
| channel_22 | YES | 5,272,893 | 90 | 90 | 90 | 0 |
| channel_23 | YES | 5,272,893 | 90 | 90 | 90 | 0 |
| channel_24 | YES | 5,272,893 | 90 | 90 | 90 | 0 |
| channel_25 | YES | 14,258,506 | 0.375 | 0.375 | 90 | 0 |
| channel_26 | YES | 14,258,506 | 0.375 | 0.375 | 90 | 0 |
| channel_27 | YES | 14,258,506 | 0.375 | 0.375 | 90 | 0 |
| channel_28 | YES | 14,258,506 | 0.375 | 0.375 | 90 | 0 |
| channel_29 | YES | 5,272,893 | 90 | 90 | 90 | 0 |
| channel_30 | YES | 5,272,893 | 90 | 90 | 90 | 0 |
| channel_31 | YES | 5,272,893 | 90 | 90 | 90 | 0 |
| channel_32 | YES | 5,272,893 | 90 | 90 | 90 | 0 |
| channel_33 | YES | 5,272,893 | 90 | 90 | 90 | 0 |
| channel_34 | YES | 14,258,506 | 0.375 | 0.375 | 90 | 0 |
| channel_35 | YES | 14,258,506 | 0.375 | 0.375 | 90 | 0 |
| channel_36 | YES | 14,258,506 | 0.375 | 0.375 | 90 | 0 |
| channel_37 | YES | 14,258,506 | 0.375 | 0.375 | 90 | 0 |
| channel_38 | YES | 5,272,893 | 90 | 90 | 90 | 0 |
| channel_39 | YES | 5,272,893 | 90 | 90 | 90 | 0 |
| channel_40 | YES | 5,272,893 | 90 | 90 | 90 | 0 |
| channel_41 | YES | 15,381,169 | 30 | 30 | 30 | 0 |
| channel_42 | YES | 15,381,169 | 30 | 30 | 30 | 0 |
| channel_43 | YES | 15,381,169 | 30 | 30 | 30 | 0 |
| channel_44 | YES | 15,381,169 | 30 | 30 | 30 | 0 |
| channel_45 | YES | 15,381,169 | 30 | 30 | 30 | 0 |
| channel_46 | YES | 15,381,169 | 30 | 30 | 30 | 0 |
| channel_47 | YES | 14,644,745 | 30 | 30 | 30 | 0 |
| channel_48 | YES | 14,644,745 | 30 | 30 | 30 | 0 |
| channel_49 | YES | 14,644,745 | 30 | 30 | 30 | 0 |
| channel_50 | YES | 4,974,682 | 90 | 89.997 | 90.003 | 0 |
| channel_51 | YES | 4,974,682 | 90 | 89.997 | 90.003 | 0 |
| channel_52 | YES | 4,974,682 | 90 | 89.997 | 90.003 | 0 |
| channel_53 | NO | 14,639,410 | 30 | 30 | 30 | 0 |
| channel_54 | NO | 14,639,410 | 30 | 30 | 30 | 0 |
| channel_55 | NO | 14,639,410 | 30 | 30 | 30 | 0 |
| channel_56 | NO | 14,639,410 | 30 | 30 | 30 | 0 |
| channel_57 | YES | 14,639,410 | 30 | 30 | 30 | 0 |
| channel_58 | YES | 14,639,410 | 30 | 30 | 30 | 0 |
| channel_59 | YES | 14,639,410 | 30 | 30 | 30 | 0 |
| channel_60 | YES | 14,639,410 | 30 | 30 | 30 | 0 |
| channel_61 | YES | 487,448 | 900 | 900 | 900 | 0 |
| channel_62 | YES | 487,448 | 900 | 900 | 900 | 0 |
| channel_63 | YES | 487,448 | 900 | 900 | 900 | 0 |
| channel_64 | YES | 4,810,995 | 157.5 | 3 | 180 | 0 |
| channel_65 | YES | 4,810,995 | 157.5 | 3 | 180 | 0 |
| channel_66 | YES | 4,810,995 | 157.5 | 3 | 180 | 0 |
| channel_67 | NO | 4,810,995 | 157.5 | 3 | 180 | 0 |
| channel_68 | NO | 4,810,995 | 157.5 | 3 | 180 | 0 |
| channel_69 | NO | 4,810,995 | 157.5 | 3 | 180 | 0 |
| channel_70 | YES | 14,670,328 | 30 | 30 | 30 | 0 |
| channel_71 | YES | 14,666,814 | 30 | 30 | 30 | 0 |
| channel_72 | YES | 14,668,450 | 30 | 30 | 30 | 0 |
| channel_73 | YES | 14,669,336 | 30 | 30 | 30 | 0 |
| channel_74 | YES | 19,286,353 | 30 | 6 | 30 | 0 |
| channel_75 | YES | 14,667,583 | 30 | 30 | 30 | 0 |
| channel_76 | YES | 14,671,647 | 30 | 30 | 30 | 0 |
