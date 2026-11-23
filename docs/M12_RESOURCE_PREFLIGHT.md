# Milestone 1.2 resource preflight

Prepared 23 November 2026, before full ingestion. Machine-readable measurements,
freeze and subsequent resource rechecks are in `artifacts/milestone12/`.

## Scope and freeze

The original source scan covers exactly **76 channels / 744,856,895 rows**.
`channels.csv` supplies identities, not observation counts; counts are taken from
the preserved complete source scan and will be independently checked against
fresh source decoding and Parquet metadata. No labels are used during ingestion.

`freeze.json` records SHA256 for all prior artifacts, all original source files,
protected application/model files and existing configurations. Exact engine
source and JSON configuration copies are in `frozen/`. The original engine
matches the completed M1.1 manifest's code hashes. No fitted models, thresholds
or detector parameters change. Existing M1/M1.1 stores and results are retained.

## Disk, memory and time estimates

| Resource | Pre-ingestion evidence / allowance |
|---|---|
| Free output disk | 366.93 GiB at first preflight |
| Existing compressed channel ZIPs | 3.51 GiB; retained in place |
| Uncompressed pickle payloads | 8.32 GiB; never all extracted to disk |
| New Parquet, central estimate | 5.46 GiB (5,864,244,787 bytes) |
| New Parquet, conservative allowance | 11.10 GiB (16 bytes per row) |
| Temporary workspace allowance | 1 GiB, one channel partial at a time |
| Free-space reserve | 10 GiB |
| Required free space | 22.10 GiB total, including output and reserves |
| Physical RAM | 15.71 GiB (nominal 16 GB machine) |
| Process peak allowance | 994.84 MiB; largest measured pilot RSS 663.227 MiB |
| Additional available-memory reserve | 512 MiB |
| Required available RAM | 1.47 GiB before each channel |
| Pilot | 59,926,812 rows / 471,802,701 Parquet bytes / 8.493 s |
| Linear time reference only | 105.56 s |
| Ingestion planning range | 3.5–10.6 minutes (2–6 times linear reference) |
| All-row integrity planning range | 2–10 additional minutes |

The five pilot channels include the largest source frame (231,436,236 bytes),
but are not a random compression or runtime sample. Their output ratios range
from 7.31 to 8.27 bytes per row. The 16-byte allowance is an engineering margin,
not a guaranteed upper bound. Cache state, filesystem contention, antivirus,
compression differences, thermal throttling and paging can alter scaling.
Integrity includes re-decoding every source, bounded Parquet scans and repeated
SHA256 reads. Snapshot/hash time is additional to the ingestion estimate.

The first live gate failed on RAM: 1.33 GiB available against 1.47 GiB required.
No ingestion was started at that point. A fresh passing gate is required before
starting, and every channel is checked again. Earlier observations near 1.9 GiB
show that available memory fluctuates with other applications. A failure pauses
the pipeline with completed channels retained; it does not kill user workloads.

The recheck at **2026-11-23 13:05:14 UTC** passed: **5.66 GiB available RAM**
and **366.93 GiB free disk**. Full ingestion was started only after this passing
preflight was presented. Both observations are retained in `preflight_history.json`.

## Proposed ingestion and required changes

Use `artifacts/milestone12/telemetry`, separate from the original pilot store.
Process one original ZIP at a time in a single worker. Pickle is not a streaming
record format: one whole source DataFrame must be decoded. Validation, Arrow
conversion and Parquet writes use **250,000-row batches**. This bounds additional
work buffers and prevents any dataset-wide pandas materialization. Timestamp UTC
nanoseconds, original numeric dtype/value and channel identity are preserved;
naive source times retain the existing documented UTC interpretation.

The existing storage implementation already supplies checkpoint manifests,
source identity checks, file SHA256 and OS writer locking. Minimal hardening adds
explicit Parquet reader closure, temporary-file `fsync`, and interruption status.
New `app.readiness` supplies the freeze, estimates, disk/RAM gates and sequential
orchestration. New `app.integrity` supplies resumable, exact all-row source/Parquet
verification. No API, database, frontend, chatbot or detector change is required.

## Recovery and integrity

Write a channel to a partial file, close and flush it, then replace its final
file atomically. Only then checkpoint the completed size, schema, row count and
SHA256. Resume checks existing completed hashes. An interrupted channel is
rewritten from its ZIP, never appended; a rename-before-checkpoint interruption
therefore cannot duplicate rows. OS locks release on process termination.

Integrity independently checks all 76 identities, manifest completeness, counts,
every timestamp and every numeric value, including dtype and finite value bits.
It checks order, duplicates, missing values, minima/maxima and time bounds across
batch boundaries. Source and Parquet SHA256 are checked before and after each
channel; verification checkpoints are reused only if matching hashes and config
remain valid. Finally, all original source files and prior artifacts are hashed
again against the freeze inventory.

## Benchmark execution design (design only)

A separate sequential runner will maintain chronological split boundaries,
causal feature/regime state and open events across batches. It will store
resumable per-channel predictions/results and keep point, interval and gap
evaluation separate. Exact disk-backed statistics are required where the
current bounded runner fits full arrays. Existing fitted configurations and
learned thresholds remain frozen; previously unfitted channels require an
explicit future calibration/transfer protocol before execution.

Dataset A contains the exposed channel 12 interval, channel 61 point and
representative prefixes. Dataset B excludes documented development windows;
neither is external blind validation. Metrics separate annotation-supported
recall from nominal-complement-assumed precision/F1/false alarms per day, use
one-to-one event matches, and retain redundant and outside-annotation events.
Target=NO remains unlabeled. Details: [benchmark design](M12_BENCHMARK_DESIGN.md).

**Stop after ingestion and integrity verification. No anomaly benchmark runs.**

Commands from `backend/`:

```powershell
.venv/Scripts/python.exe -m app.readiness preflight
.venv/Scripts/python.exe -m app.readiness ingest
.venv/Scripts/python.exe -m app.readiness verify
.venv/Scripts/python.exe -m app.readiness preservation
```
