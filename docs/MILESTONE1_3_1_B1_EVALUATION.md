# M1.3.1 — First predeclared B1 evaluation

Run #11, channel_13; evaluated code checkpoint efce54a60cb94cae0cadcbcf0f7be217e7ce5c6a.
Selection: lowest-numbered Target=YES B1 channel after excluding the five A-exposed channels, before outcomes were inspected.

## Engineering result

Completed with all six comparator streams scoring all 2,851,702 test observations, no unsupported comparators, timestamp-only history capacity 7,242 rows within the existing 10,000-row budget, and no resampling or label-driven calibration. Wall time: 4052.051 s; peak sampled RSS: 439.137 MiB. The product export contains 7,747 combined incident records, none with annotation IDs.

## Scientific result

| Model | Predicted events | Matched annotated events | Labelled sample recall |
|---|---:|---:|---:|
| Robust statistical | 377295 | 1/1 | 24.2087% |
| Isolation Forest | 31148 | 1/1 | 0.7620% |
| Temporal point | 7747 | 0/1 | 0% |
| Temporal interval | 0 | 0/1 | 0% |
| Improved temporal | 7747 | 0/1 | 0% |
| Combined M1.3.1 | 7747 | 0/1 | 0% |

Combined burden: 25.2395 incidents per observation day; 15,398 flagged test samples (0.5400%). All 7,747 unmatched incidents have unknown physical truth; under nominal complement only, these are treated as false positives. Supported precision and F1 are unavailable; no independently confirmed negative observations were provided.

The one annotated held-out rare event (id_180) spans 1,706 positive observations. Both statistical and Isolation Forest streams overlapped this annotation, while the temporal-first operator policy did not. The stricter operator rule reduced the number of operator candidates relative to the independent IF stream, but did not establish improved anomaly detection. The channel was previously unexposed for detector development, but id_180 also appears in CH-12, so this does not establish independence of the physical event.

## Decision

Preserve Run #10 and Run #11 unchanged. Retain M1.3.1 as an evaluated research prototype, not a flight-qualified or externally blind-validated detector. Do not tune using CH-13 test labels and then call the result held-out. A future M1.3.2 detector-quality study requires a newly frozen method and fresh evaluation. Full 76-channel ingestion is established; full 76-channel modeling remains unvalidated.

Sources: Run #11 report.json, product_summary.json, execution.json, run_configuration.json, history_compatibility.json, incident_events.jsonl; first B1 predeclaration.
