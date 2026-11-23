# Detection comparison — measured Milestone 1.1 results

All candidates within a case use identical chronological timestamps. Primary split: 60/20/20. Secondary split: 50/20/30 preserves the original 6000-row holdout. Splits are reported separately; no winner or hyperparameter was chosen using final labels.

Precision/F1/false alarms below use the official nominal-complement convention **as an explicit assumption** on labelled channels. Annotation-supported recall and label-independent burden are separately available in every case report. A dash means unavailable, including recall/F1 when the final partition has no positive truth. These are development-exposed, selection-biased diagnostic windows, not a blind full benchmark.

## Same original holdouts: historical before/after

| Diagnostic | Model | Sample precision | Sample recall | Sample F1 | Event precision | Event recall | Event F1 | Unmatched events |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| channel_12 | M1 combined | 0.0358 | 0.1508 | 0.0578 | 0.0013 | 1.0000 | 0.0026 | 782 |
| channel_12 | M1.1 robust_statistical | 0.0358 | 0.1508 | 0.0578 | 0.0013 | 1.0000 | 0.0027 | 748 |
| channel_12 | M1.1 isolation_forest | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 36 |
| channel_12 | M1.1 temporal_point | 0.1915 | 0.0209 | 0.0377 | 0.0233 | 1.0000 | 0.0455 | 42 |
| channel_12 | M1.1 temporal_interval | 0.8307 | 0.9907 | 0.9037 | 0.2500 | 1.0000 | 0.4000 | 3 |
| channel_12 | M1.1 improved_temporal | 0.7744 | 0.9954 | 0.8711 | 0.0233 | 1.0000 | 0.0455 | 42 |
| channel_12 | M1.1 combined | 0.7744 | 0.9954 | 0.8711 | 0.0233 | 1.0000 | 0.0455 | 42 |
| channel_61 | M1 combined | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 20 |
| channel_61 | M1.1 robust_statistical | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 20 |
| channel_61 | M1.1 isolation_forest | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0 |
| channel_61 | M1.1 temporal_point | 0.5000 | 1.0000 | 0.6667 | 0.5000 | 1.0000 | 0.6667 | 1 |
| channel_61 | M1.1 temporal_interval | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0 |
| channel_61 | M1.1 improved_temporal | 0.5000 | 1.0000 | 0.6667 | 0.5000 | 1.0000 | 0.6667 | 1 |
| channel_61 | M1.1 combined | 0.5000 | 1.0000 | 0.6667 | 0.5000 | 1.0000 | 0.6667 | 1 |

The historical M1 model used the whole 70% prefix for training. M1.1 divides that prefix into 50% training and 20% validation. Its baseline sample flags remain directly comparable; cadence-aware grouping can change event counts. The contemporary candidate tables below are the fair comparisons with identical fitting/calibration partitions. Do not attribute every historical difference solely to the detector.

On the interval diagnostic, the interval-specific strategy detects sustained behaviour with fewer events than the general point+interval union. On prefix windows, adding IF sometimes increases burden; channel74's combined candidate emits 262 events versus 97 for improved temporal and 2 for the statistical candidate on the 50/20/30 split. No model is declared universally best.

The channel61 point lies in validation under 60/20/20, so its primary final partition has no point event and no supported recall estimate. The predeclared 50/20/30 regression split places it in the same final holdout as M1. Both outcomes are retained.

## Every measured comparison

S-P/R/F1 are sample metrics; E-P/R/F1 are strict one-to-one event metrics. Runtime sums measured dependent processing stages (shared features reused); memory is sampled absolute process RSS, not isolated per-model allocation. Evaluation and artifact writing are outside per-model stage times; full experiment time includes them. PCA includes validation scoring. No GPU was used.

### prefix_channel_1/60_20_20

Final range: `2000-01-17T16:00:02.805000+00:00` through `2000-01-21T19:58:32.802000+00:00`; 4,000 rows.

| Model | S-P | S-R | S-F1 | E-P | E-R | E-F1 | Assumed FA/day | Events | Seconds | Peak RSS MiB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| robust_statistical | — | — | — | — | — | — | — | 1 | 1.031 | 199.10 |
| isolation_forest | — | — | — | — | — | — | — | 0 | 1.147 | 199.10 |
| temporal_point | — | — | — | — | — | — | — | 1 | 0.388 | 199.52 |
| temporal_interval | — | — | — | — | — | — | — | 0 | 0.388 | 199.52 |
| improved_temporal | — | — | — | — | — | — | — | 1 | 0.388 | 199.52 |
| combined | — | — | — | — | — | — | — | 1 | 1.535 | 199.52 |

### prefix_channel_1/50_20_30

Final range: `2000-01-15T14:00:02.805000+00:00` through `2000-01-21T19:58:32.802000+00:00`; 6,000 rows.

| Model | S-P | S-R | S-F1 | E-P | E-R | E-F1 | Assumed FA/day | Events | Seconds | Peak RSS MiB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| robust_statistical | — | — | — | — | — | — | — | 1 | 1.115 | 200.29 |
| isolation_forest | — | — | — | — | — | — | — | 0 | 1.235 | 200.29 |
| temporal_point | — | — | — | — | — | — | — | 1 | 0.419 | 201.01 |
| temporal_interval | — | — | — | — | — | — | — | 0 | 0.419 | 201.01 |
| improved_temporal | — | — | — | — | — | — | — | 1 | 0.419 | 201.01 |
| combined | — | — | — | — | — | — | — | 1 | 1.654 | 201.01 |

### prefix_channel_12/60_20_20

Final range: `2000-01-17T16:00:06.633000+00:00` through `2000-01-21T19:58:36.633000+00:00`; 4,000 rows.

| Model | S-P | S-R | S-F1 | E-P | E-R | E-F1 | Assumed FA/day | Events | Seconds | Peak RSS MiB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| robust_statistical | 0.0000 | — | — | 0.0000 | — | — | 132.9932 | 554 | 1.172 | 202.69 |
| isolation_forest | 0.0000 | — | — | 0.0000 | — | — | 6.9617 | 29 | 1.268 | 202.69 |
| temporal_point | 0.0000 | — | — | 0.0000 | — | — | 6.4816 | 27 | 0.610 | 204.44 |
| temporal_interval | 0.0000 | — | — | 0.0000 | — | — | 0.0000 | 0 | 0.609 | 204.44 |
| improved_temporal | 0.0000 | — | — | 0.0000 | — | — | 6.4816 | 27 | 0.610 | 204.44 |
| combined | 0.0000 | — | — | 0.0000 | — | — | 6.9617 | 29 | 1.877 | 204.44 |

### prefix_channel_12/50_20_30

Final range: `2000-01-15T14:00:06.633000+00:00` through `2000-01-21T19:58:36.633000+00:00`; 6,000 rows.

| Model | S-P | S-R | S-F1 | E-P | E-R | E-F1 | Assumed FA/day | Events | Seconds | Peak RSS MiB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| robust_statistical | 0.0000 | — | — | 0.0000 | — | — | 127.8613 | 799 | 1.130 | 202.87 |
| isolation_forest | 0.0000 | — | — | 0.0000 | — | — | 12.6421 | 79 | 1.227 | 202.87 |
| temporal_point | 0.0000 | — | — | 0.0000 | — | — | 6.5611 | 41 | 0.580 | 203.60 |
| temporal_interval | 0.0000 | — | — | 0.0000 | — | — | 0.0000 | 0 | 0.579 | 203.60 |
| improved_temporal | 0.0000 | — | — | 0.0000 | — | — | 6.5611 | 41 | 0.580 | 203.60 |
| combined | 0.0000 | — | — | 0.0000 | — | — | 12.9622 | 81 | 1.806 | 203.60 |

### prefix_channel_41/60_20_20

Final range: `2000-01-06T06:59:16.353000+00:00` through `2000-01-07T14:43:16.350000+00:00`; 4,000 rows.

| Model | S-P | S-R | S-F1 | E-P | E-R | E-F1 | Assumed FA/day | Events | Seconds | Peak RSS MiB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| robust_statistical | 0.0000 | — | — | 0.0000 | — | — | 24.9580 | 33 | 1.081 | 205.27 |
| isolation_forest | 0.0000 | — | — | 0.0000 | — | — | 24.2017 | 32 | 1.225 | 206.25 |
| temporal_point | 0.0000 | — | — | 0.0000 | — | — | 16.6387 | 22 | 0.673 | 208.09 |
| temporal_interval | 0.0000 | — | — | 0.0000 | — | — | 0.0000 | 0 | 0.672 | 208.09 |
| improved_temporal | 0.0000 | — | — | 0.0000 | — | — | 16.6387 | 22 | 0.673 | 208.09 |
| combined | 0.0000 | — | — | 0.0000 | — | — | 31.0084 | 41 | 1.897 | 208.09 |

### prefix_channel_41/50_20_30

Final range: `2000-01-05T15:06:46.353000+00:00` through `2000-01-07T14:43:16.350000+00:00`; 6,000 rows.

| Model | S-P | S-R | S-F1 | E-P | E-R | E-F1 | Assumed FA/day | Events | Seconds | Peak RSS MiB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| robust_statistical | 0.0000 | — | — | 0.0000 | — | — | 25.2057 | 50 | 1.094 | 204.60 |
| isolation_forest | 0.0000 | — | — | 0.0000 | — | — | 33.7756 | 67 | 1.247 | 204.60 |
| temporal_point | 0.0000 | — | — | 0.0000 | — | — | 28.7345 | 57 | 0.681 | 205.44 |
| temporal_interval | 0.0000 | — | — | 0.0000 | — | — | 0.0000 | 0 | 0.679 | 205.44 |
| improved_temporal | 0.0000 | — | — | 0.0000 | — | — | 28.7345 | 57 | 0.681 | 205.44 |
| combined | 0.0000 | — | — | 0.0000 | — | — | 43.8579 | 87 | 1.927 | 205.44 |

### prefix_channel_61/60_20_20

Final range: `2000-06-17T12:12:57.159000+00:00` through `2000-07-29T03:57:57.156000+00:00`; 4,000 rows.

| Model | S-P | S-R | S-F1 | E-P | E-R | E-F1 | Assumed FA/day | Events | Seconds | Peak RSS MiB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| robust_statistical | 0.0000 | — | — | 0.0000 | — | — | 0.3361 | 14 | 1.026 | 206.60 |
| isolation_forest | 0.0000 | — | — | 0.0000 | — | — | 0.3361 | 14 | 1.150 | 206.88 |
| temporal_point | 0.0000 | — | — | 0.0000 | — | — | 0.0000 | 0 | 0.487 | 208.13 |
| temporal_interval | 0.0000 | — | — | 0.0000 | — | — | 0.0240 | 1 | 0.545 | 208.13 |
| improved_temporal | 0.0000 | — | — | 0.0000 | — | — | 0.0240 | 1 | 0.544 | 208.13 |
| combined | 0.0000 | — | — | 0.0000 | — | — | 0.0240 | 1 | 1.688 | 208.13 |

### prefix_channel_61/50_20_30

Final range: `2000-05-27T16:12:57.162000+00:00` through `2000-07-29T03:57:57.156000+00:00`; 6,000 rows.

| Model | S-P | S-R | S-F1 | E-P | E-R | E-F1 | Assumed FA/day | Events | Seconds | Peak RSS MiB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| robust_statistical | 0.0000 | — | — | 0.0000 | — | — | 0.3361 | 21 | 1.050 | 204.93 |
| isolation_forest | 0.0000 | — | — | 0.0000 | — | — | 0.3361 | 21 | 1.168 | 204.93 |
| temporal_point | 0.0000 | — | — | 0.0000 | — | — | 0.0000 | 0 | 0.494 | 205.41 |
| temporal_interval | 0.0000 | — | — | 0.0000 | — | — | 0.0160 | 1 | 0.586 | 205.41 |
| improved_temporal | 0.0000 | — | — | 0.0000 | — | — | 0.0160 | 1 | 0.584 | 205.41 |
| combined | 0.0000 | — | — | 0.0000 | — | — | 0.0160 | 1 | 1.745 | 205.41 |

### prefix_channel_74/60_20_20

Final range: `2000-01-01T13:20:00.969000+00:00` through `2000-01-01T16:39:57.969000+00:00`; 4,000 rows.

| Model | S-P | S-R | S-F1 | E-P | E-R | E-F1 | Assumed FA/day | Events | Seconds | Peak RSS MiB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| robust_statistical | 0.0000 | — | — | 0.0000 | — | — | 0.0000 | 0 | 1.064 | 205.36 |
| isolation_forest | 0.0000 | — | — | 0.0000 | — | — | 1490.7727 | 207 | 1.211 | 206.60 |
| temporal_point | 0.0000 | — | — | 0.0000 | — | — | 374.4936 | 52 | 0.601 | 208.25 |
| temporal_interval | 0.0000 | — | — | 0.0000 | — | — | 0.0000 | 0 | 0.600 | 208.25 |
| improved_temporal | 0.0000 | — | — | 0.0000 | — | — | 374.4936 | 52 | 0.602 | 208.25 |
| combined | 0.0000 | — | — | 0.0000 | — | — | 1325.1313 | 184 | 1.811 | 208.25 |

### prefix_channel_74/50_20_30

Final range: `2000-01-01T11:40:00.969000+00:00` through `2000-01-01T16:39:57.969000+00:00`; 6,000 rows.

| Model | S-P | S-R | S-F1 | E-P | E-R | E-F1 | Assumed FA/day | Events | Seconds | Peak RSS MiB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| robust_statistical | 0.0000 | — | — | 0.0000 | — | — | 9.6016 | 2 | 1.049 | 205.60 |
| isolation_forest | 0.0000 | — | — | 0.0000 | — | — | 1296.2160 | 270 | 1.206 | 205.60 |
| temporal_point | 0.0000 | — | — | 0.0000 | — | — | 465.6776 | 97 | 0.587 | 206.59 |
| temporal_interval | 0.0000 | — | — | 0.0000 | — | — | 0.0000 | 0 | 0.585 | 206.59 |
| improved_temporal | 0.0000 | — | — | 0.0000 | — | — | 465.6776 | 97 | 0.587 | 206.59 |
| combined | 0.0000 | — | — | 0.0000 | — | — | 1257.8096 | 262 | 1.791 | 206.59 |

### interval_channel_12/60_20_20

Final range: `2000-03-17T16:00:06.627000+00:00` through `2000-03-23T04:45:18.624000+00:00`; 4,000 rows.

| Model | S-P | S-R | S-F1 | E-P | E-R | E-F1 | Assumed FA/day | Events | Seconds | Peak RSS MiB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| robust_statistical | 0.0545 | 0.1508 | 0.0800 | 0.0021 | 1.0000 | 0.0042 | 86.3942 | 476 | 1.067 | 205.93 |
| isolation_forest | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 4.9108 | 27 | 1.170 | 207.17 |
| temporal_point | 0.2500 | 0.0209 | 0.0385 | 0.0312 | 1.0000 | 0.0606 | 5.6384 | 32 | 0.594 | 208.48 |
| temporal_interval | 0.8307 | 0.9907 | 0.9037 | 0.2500 | 1.0000 | 0.4000 | 0.5456 | 4 | 0.601 | 208.48 |
| improved_temporal | 0.7901 | 0.9954 | 0.8809 | 0.0312 | 1.0000 | 0.0606 | 5.6384 | 32 | 0.601 | 208.48 |
| combined | 0.7901 | 0.9954 | 0.8809 | 0.0312 | 1.0000 | 0.0606 | 5.6384 | 32 | 1.770 | 208.48 |

### interval_channel_12/50_20_30

Final range: `2000-03-15T14:00:06.627000+00:00` through `2000-03-23T04:45:18.624000+00:00`; 6,000 rows.

| Model | S-P | S-R | S-F1 | E-P | E-R | E-F1 | Assumed FA/day | Events | Seconds | Peak RSS MiB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| robust_statistical | 0.0358 | 0.1508 | 0.0578 | 0.0013 | 1.0000 | 0.0027 | 98.6627 | 749 | 1.099 | 205.36 |
| isolation_forest | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 4.7485 | 36 | 1.196 | 205.36 |
| temporal_point | 0.1915 | 0.0209 | 0.0377 | 0.0233 | 1.0000 | 0.0455 | 5.5399 | 43 | 0.610 | 211.68 |
| temporal_interval | 0.8307 | 0.9907 | 0.9037 | 0.2500 | 1.0000 | 0.4000 | 0.3957 | 4 | 0.616 | 211.68 |
| improved_temporal | 0.7744 | 0.9954 | 0.8711 | 0.0233 | 1.0000 | 0.0455 | 5.5399 | 43 | 0.617 | 211.68 |
| combined | 0.7744 | 0.9954 | 0.8711 | 0.0233 | 1.0000 | 0.0455 | 5.5399 | 43 | 1.812 | 211.68 |

### point_channel_61/60_20_20

Final range: `2007-04-19T07:42:23.862000+00:00` through `2007-05-30T23:12:23.853000+00:00`; 4,000 rows.

| Model | S-P | S-R | S-F1 | E-P | E-R | E-F1 | Assumed FA/day | Events | Seconds | Peak RSS MiB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| robust_statistical | 0.0000 | — | — | 0.0000 | — | — | 0.3362 | 14 | 1.020 | 206.66 |
| isolation_forest | 0.0000 | — | — | 0.0000 | — | — | 0.0000 | 0 | 1.128 | 207.75 |
| temporal_point | 0.0000 | — | — | 0.0000 | — | — | 0.0000 | 0 | 0.457 | 210.19 |
| temporal_interval | 0.0000 | — | — | 0.0000 | — | — | 0.0000 | 0 | 0.457 | 210.19 |
| improved_temporal | 0.0000 | — | — | 0.0000 | — | — | 0.0000 | 0 | 0.457 | 210.19 |
| combined | 0.0000 | — | — | 0.0000 | — | — | 0.0000 | 0 | 1.585 | 210.19 |

### point_channel_61/50_20_30

Final range: `2007-03-26T19:45:17.865000+00:00` through `2007-05-30T23:12:23.853000+00:00`; 6,000 rows.

| Model | S-P | S-R | S-F1 | E-P | E-R | E-F1 | Assumed FA/day | Events | Seconds | Peak RSS MiB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| robust_statistical | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.3202 | 20 | 1.066 | 206.19 |
| isolation_forest | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0 | 1.182 | 206.19 |
| temporal_point | 0.5000 | 1.0000 | 0.6667 | 0.5000 | 1.0000 | 0.6667 | 0.0160 | 2 | 0.480 | 206.22 |
| temporal_interval | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0 | 0.480 | 206.22 |
| improved_temporal | 0.5000 | 1.0000 | 0.6667 | 0.5000 | 1.0000 | 0.6667 | 0.0160 | 2 | 0.480 | 206.22 |
| combined | 0.5000 | 1.0000 | 0.6667 | 0.5000 | 1.0000 | 0.6667 | 0.0160 | 2 | 1.662 | 206.22 |

### pca_aligned_channel_41/60_20_20

Final range: `2000-01-01T13:20:30+00:00` through `2000-01-01T16:40:00+00:00`; 400 rows.

| Model | S-P | S-R | S-F1 | E-P | E-R | E-F1 | Assumed FA/day | Events | Seconds | Peak RSS MiB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| robust_statistical | 0.0000 | — | — | 0.0000 | — | — | 0.0000 | 0 | 0.114 | 208.38 |
| isolation_forest | 0.0000 | — | — | 0.0000 | — | — | 7.2180 | 1 | 0.201 | 208.38 |
| temporal_point | 0.0000 | — | — | 0.0000 | — | — | 28.8722 | 4 | 0.062 | 208.39 |
| temporal_interval | 0.0000 | — | — | 0.0000 | — | — | 0.0000 | 0 | 0.062 | 208.39 |
| improved_temporal | 0.0000 | — | — | 0.0000 | — | — | 28.8722 | 4 | 0.062 | 208.39 |
| combined | 0.0000 | — | — | 0.0000 | — | — | 28.8722 | 4 | 0.263 | 208.39 |
| pca_experimental | 0.0000 | — | — | 0.0000 | — | — | 28.8722 | 4 | 0.007 | 208.39 |

### pca_aligned_channel_74/60_20_20

Final range: `2000-01-01T13:20:30+00:00` through `2000-01-01T16:40:00+00:00`; 400 rows.

| Model | S-P | S-R | S-F1 | E-P | E-R | E-F1 | Assumed FA/day | Events | Seconds | Peak RSS MiB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| robust_statistical | 0.0000 | — | — | 0.0000 | — | — | 0.0000 | 0 | 0.113 | 204.19 |
| isolation_forest | 0.0000 | — | — | 0.0000 | — | — | 137.1429 | 19 | 0.201 | 204.19 |
| temporal_point | 0.0000 | — | — | 0.0000 | — | — | 57.7444 | 8 | 0.062 | 204.19 |
| temporal_interval | 0.0000 | — | — | 0.0000 | — | — | 0.0000 | 0 | 0.062 | 204.19 |
| improved_temporal | 0.0000 | — | — | 0.0000 | — | — | 57.7444 | 8 | 0.062 | 204.19 |
| combined | 0.0000 | — | — | 0.0000 | — | — | 137.1429 | 19 | 0.263 | 204.19 |
| pca_experimental | 0.0000 | — | — | 0.0000 | — | — | 28.8722 | 4 | 0.007 | 204.19 |

### pca_aligned_channel_41/50_20_30

Final range: `2000-01-01T11:40:30+00:00` through `2000-01-01T16:40:00+00:00`; 600 rows.

| Model | S-P | S-R | S-F1 | E-P | E-R | E-F1 | Assumed FA/day | Events | Seconds | Peak RSS MiB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| robust_statistical | 0.0000 | — | — | 0.0000 | — | — | 0.0000 | 0 | 0.114 | 204.65 |
| isolation_forest | 0.0000 | — | — | 0.0000 | — | — | 9.6160 | 2 | 0.200 | 204.65 |
| temporal_point | 0.0000 | — | — | 0.0000 | — | — | 19.2321 | 4 | 0.061 | 204.65 |
| temporal_interval | 0.0000 | — | — | 0.0000 | — | — | 0.0000 | 0 | 0.061 | 204.65 |
| improved_temporal | 0.0000 | — | — | 0.0000 | — | — | 19.2321 | 4 | 0.061 | 204.65 |
| combined | 0.0000 | — | — | 0.0000 | — | — | 19.2321 | 4 | 0.261 | 204.65 |
| pca_experimental | 0.0000 | — | — | 0.0000 | — | — | 24.0401 | 5 | 0.007 | 204.65 |

### pca_aligned_channel_74/50_20_30

Final range: `2000-01-01T11:40:30+00:00` through `2000-01-01T16:40:00+00:00`; 600 rows.

| Model | S-P | S-R | S-F1 | E-P | E-R | E-F1 | Assumed FA/day | Events | Seconds | Peak RSS MiB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| robust_statistical | 0.0000 | — | — | 0.0000 | — | — | 0.0000 | 0 | 0.118 | 204.75 |
| isolation_forest | 0.0000 | — | — | 0.0000 | — | — | 105.7763 | 22 | 0.208 | 204.75 |
| temporal_point | 0.0000 | — | — | 0.0000 | — | — | 14.4240 | 3 | 0.061 | 204.81 |
| temporal_interval | 0.0000 | — | — | 0.0000 | — | — | 0.0000 | 0 | 0.061 | 204.81 |
| improved_temporal | 0.0000 | — | — | 0.0000 | — | — | 14.4240 | 3 | 0.061 | 204.81 |
| combined | 0.0000 | — | — | 0.0000 | — | — | 105.7763 | 22 | 0.269 | 204.81 |
| pca_experimental | 0.0000 | — | — | 0.0000 | — | — | 24.0401 | 5 | 0.007 | 204.81 |

PCA is an additional controlled comparison on 2000 common 30-second bins from channels41/74, which share the same anonymous physical-unit token. They belong to different subsystems; engineering correlation is not asserted. Every comparator in each PCA case uses the same aligned timestamps. Causal bins exclude their right endpoint; no interpolation/backfill occurs. This alignment is not compared as though it were the unresampled20,000-row task. These aligned prefix tests contain no positive truth, so PCA anomaly recall remains unestablished.

Random Forest was skipped: the selected chronological training windows have no positive value-annotation events, and no independently confirmed normal training examples were supplied. Nominal-complement assumptions were not silently converted into supervised labels.

[Machine-readable comparison](../artifacts/milestone11/reports/detection_comparison.json) · [Run manifest](../artifacts/milestone11/comparison_final/manifest.json)
