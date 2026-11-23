# Milestone 1.2 — complete dataset ingestion and benchmark readiness

Completed **23 November 2026**. All **76 channels / 744,856,895 observations**
were ingested and independently verified against the original ZIP archives.
**The full anomaly benchmark has not been executed.** Work stops here for review.

## Delivered evidence

| Artifact | Purpose |
|---|---|
| [Resource preflight](M12_RESOURCE_PREFLIGHT.md) | Disk/RAM gates, uncertainty, runtime estimates and recovery plan |
| [Machine-readable preflight](../artifacts/milestone12/preflight.json) | Passing measurements recorded before ingestion |
| [Preflight history](../artifacts/milestone12/preflight_history.json) | Initial low-RAM rejection and later passing recheck |
| [Freeze inventory](../artifacts/milestone12/freeze.json) | Configuration, original source, prior artifact and protected-code SHA256 records |
| [New ingestion manifest](../artifacts/milestone12/telemetry/manifest.json) | All 76 Parquet files, channel identities, statistics and SHA256 |
| [Integrity report](../artifacts/milestone12/integrity/integrity_report.json) | Exhaustive per-channel source-to-Parquet checks and resource measurements |
| [Preservation report](../artifacts/milestone12/preservation_report.json) | Original files and prior artifacts unchanged |
| [Completion summary](../artifacts/milestone12/completion_summary.json) | Compact machine-readable totals, resources and remaining risks |
| [Benchmark design](M12_BENCHMARK_DESIGN.md) | Separate streaming runner architecture, exposure separation and metric definitions |
| [Benchmark protocol](../artifacts/milestone12/benchmark_protocol.json) | Frozen settings, exact diagnostic windows and proposed chronological split ordinals |
| [Regression results](../artifacts/milestone12/validation/pytest.xml) | 144 passing tests |

## Integrity result

- Expected, ingested and verified channels: **76 / 76 / 76**. The catalog,
  manifest and Parquet file sets match exactly.
- Expected, ingested and verified rows: **744,856,895** in each case. Counts match
  the prior complete source profile and a fresh decode of each source. The
  original catalog itself does not contain row counts.
- Every timestamp matches in UTC nanoseconds; every finite numeric value matches
  bit for bit. All channel value columns remain **float32**. Original source
  timestamps are naive and retain the established UTC interpretation.
- All channels have strictly increasing, unique timestamps. Duplicate timestamps,
  missing timestamps, missing values and infinite values: **0**.
- Earliest observation across channels: **2000-01-01T00:00:00.969Z**.
  Latest: **2013-12-31T23:59:59.937Z**. Per-channel endpoints and numeric minima/
  maxima are retained in the machine-readable report and matched to the source.
- Parquet SHA256 matches each completed manifest entry. Source and Parquet bytes
  were hashed before and after each full comparison. No partial files remain.
- Verification compared every row; it was not a sample or a footer-only check.

## Measured resources

| Stage / resource | Actual |
|---|---:|
| Ingestion wall time, including final completed-file hash/reuse pass | **107.724 s** |
| Ingestion sampled peak process RSS | **514.582 MiB** |
| Full integrity wall time | **73.374 s** |
| Integrity sampled peak process RSS | **620.855 MiB** |
| Sum of measured ingestion and verification stages | **181.098 s** |
| Parquet bytes | **5,876,817,698 bytes / 5.47 GiB** |
| Largest single Parquet file | **156,426,827 bytes / 149.18 MiB** |
| Free disk after ingestion | **388,115,779,584 bytes / 361.46 GiB** |
| Minimum available RAM observed at ingestion channel gates | **5.17 GiB** |
| Ingestion resource gates passed | **76 / 76** |

RSS is sampled every 50 ms and can miss short spikes; it includes native Arrow
allocations. These are stage timings, not total interactive elapsed time: they
exclude planning, snapshot/preservation hashing and tests. Test execution took
34.57 s. No concurrent heavy tests ran during the measured ingestion or integrity
stages. Actual time was below the conservative planning ranges; that does not
establish linear performance on other machines or under memory pressure.

The new output is 0.21% above the pilot-based central estimate and below the
11.10 GiB output allowance. Only one temporary Parquet is written at a time;
its final maximum size is 149.18 MiB. That is a bound inferred from sequential
file writes and completed sizes, not an independently sampled temporary-space
peak. Original archives are neither extracted wholesale nor modified.

## Preservation and implementation

The post-run SHA256 check verified **385 existing artifact files**, **778 original
source files**, **43 protected application/configuration/document files**, and
**98 frozen copies**. The freeze includes **76 configuration/manifest JSON
files**, including existing detector configurations and learned calibration
thresholds. No old artifact, detector parameter, threshold or model was changed.
All new telemetry output is under `artifacts/milestone12/telemetry`; the original
five-channel store remains intact.

`app.readiness` adds an immutable initial freeze, empirical resource estimates,
live gates and sequential orchestration. `app.integrity` adds full-row verification
with atomic per-channel checkpoints and hash-validated recovery. Changes to
`storage.py` are limited to closing readers explicitly, flushing partial Parquet
files before atomic replacement, and checkpointing process interruptions. No
frontend, chatbot, production database or API contract work was performed.

The source format is a monolithic pickle per ZIP. One complete source channel
must be decoded in memory; validation/conversion/writing/Parquet comparison use
250,000-row batches. There is no dataset-wide DataFrame. This exception to true
row streaming is explicit and stayed well within the measured memory budget.

Interrupted ingestion retries the current channel from its original ZIP and
never appends to a partial file. Existing completed files are accepted only after
size/footer/SHA checks. The real run's final pass hash-checked and reused all 76
files. Integrity checkpoints similarly require matching source/output/config
hashes; an interrupted or failed channel is recomputed.

For byte-identified M1.1 replay, use the archived `frozen/backend/app` source
directory in an isolated replay workspace with the existing backend interpreter
and dependencies. The old manifests identify the complete original app source
set; adding M1.2 modules changes that set's identity. Do not edit old manifests
or mix new modules into the archived app directory to bypass this check. Write
any future diagnostic replay into a new output directory.

## Validation and remaining risks

**144 tests passed; four pre-existing dependency/deprecation warnings.** Added
tests cover corrupted values/timestamps/schema/counts/hashes, missing/incomplete
manifests, exact all-row recovery, resource-gate interruption, active writer locks,
source mutation, same-size byte tampering, partial-write restart, KeyboardInterrupt,
and early reader closure. Tests use temporary synthetic datasets.

No anomaly performance metrics are newly reported: the benchmark design is
complete for review, while its runner remains to be implemented. Its protocol
separates exposed development diagnostics (A) from other retrospective windows
(B); neither is external blind validation. Target=NO remains unknown, never a
supervised normal label. Annotation-supported recall and nominal-complement
precision/F1/false alarms per day remain separate, as do point, interval and gap
tasks, redundant overlaps and outside-annotation burden.

Before a later benchmark, resolve the transfer of existing fitted artifacts
versus new train/validation-only fits under a frozen procedure. Implement exact
disk-backed statistics/calibration, causal checkpoint serialization, streaming
evaluation and a parity-tested event-grouping adapter. The frozen legacy feature
history guard can fail in dense regimes, and temporal event grouping can vary
with batch boundaries during cadence changes. Neither is silently changed here.
Benchmark time, temporary storage and prediction volume need their own measured
preflight. Available RAM can change with other workloads; keep the live gates.

**Stop condition satisfied: full ingestion and integrity complete; benchmark not run.**
