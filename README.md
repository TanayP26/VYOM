# VYOM — Spacecraft Telemetry Intelligence

VYOM is an academic research platform for retrospective spacecraft telemetry analysis, anomaly investigation and evidence-grounded decision support. It uses the ESA Anomaly Detection Benchmark (Mission 1), statistical machine learning, a memory-bounded streaming pipeline and a React/FastAPI workspace.

**Research release candidate v2.0.0.** Not flight-qualified, not a live spacecraft monitoring service, and no spacecraft-command capability.

## What is implemented

- All 76 Mission 1 channels ingested into Parquet: 744,856,895 observations (approximately 5.47 GiB).
- Chronological 60/20/20 protocol with exact training statistics and label-free validation calibration.
- Cadence-aware temporal point and persistent interval scoring, robust statistical and Isolation Forest comparators, timestamp-gap candidates and event grouping across batches.
- Active M1.3.1 operator policy: temporal point OR persistent temporal interval; Isolation Forest remains an independent comparator.
- Memory-bounded checkpointed execution, persisted incident evidence and per-channel scientific reports.
- Eight-view React workspace, telemetry inspection, bounded incident search and pagination, evidence assistant and optional external research.
- Optional Nebius inference, LangSmith tracing and Tavily research. Provider configuration is not equivalent to verified connectivity.

## Evaluation

| Evidence | Run #10 | Run #11 |
|---|---|---|
| Channel | CH-12 | CH-13 |
| Policy | M1.3.0 | M1.3.1 |
| Test observations | 2,851,702 | 2,851,702 |
| Combined predicted events | 31,308 | 7,747 |
| Annotated event recall | 1/1 | 0/1 |
| Labelled sample recall | 2/1,727 | 0/1,706 |
| Peak sampled RSS | 435.836 MiB | 439.137 MiB |

These are separate retrospective channel evaluations, not a controlled before/after comparison. The annotation id_180 occurs in both channels, so physical-event independence is not established. Unmatched candidates have unknown physical truth; supported precision and F1 are unavailable without independently confirmed negatives. Full-mission ingestion does not establish full-mission detection performance.

The verified release candidate passed 293 backend regression tests, dependency checks and the TypeScript/Vite production build on Windows. The scientific engine remains frozen at efce54a; the UI/product release candidate is a9ebeed. These tests verify implementation, not operational detection quality.

Read [scientific protocol](docs/SCIENTIFIC_PROTOCOL.md), [operator policy](docs/MILESTONE1_3_1_OPERATOR_POLICY.md) and [B1 evaluation](docs/MILESTONE1_3_1_B1_EVALUATION.md).

## Local setup

The ESA dataset, Parquet store, run artifacts and SQLite database are intentionally not committed. Obtain the original ESA data separately and retain the existing M1.2 ingestion output. Without local data, the UI cannot reproduce the mission evidence or historical runs.

From the repository root, in PowerShell:

```powershell
cd backend
python -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
cd ..\frontend
npm ci
cd ..
.\scripts\verify_windows.ps1
.\scripts\run_windows.ps1
```

Use the existing environment if already configured. Set the dataset/store paths in backend/.env:

```dotenv
DATASET_DIR=../data/esa_adb/mission1/ESA-Mission1
TELEMETRY_STORE_DIR=../artifacts/milestone12/telemetry
ARTIFACT_DIR=../artifacts/final
```

UI: http://localhost:5173 · API documentation: http://localhost:8000/docs.

## Optional intelligence providers

In backend/.env, configure the following only if you have the corresponding credentials. Never commit credentials.

```dotenv
NEBIUS_BASE_URL=https://api.tokenfactory.nebius.com/v1/
NEBIUS_API_KEY=
NEBIUS_MODEL=Qwen/Qwen3-235B-A22B-Instruct-2507
TAVILY_API_KEY=
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=VYOM
```

Use an exact model ID returned by your provider's model catalog; availability may change. The assistant retrieves internal documents, while Tavily research remains explicitly external. No model training is delegated to the assistant. Restart the backend after modifying configuration.

## Deployment and safety

See [deployment checklist](docs/RELEASE_DEPLOYMENT.md). Native Windows execution is verified; container execution and public hosting require separate verification. Do not expose the API publicly without authentication, authorization, rate limits, restricted data access and an appropriate persistence and cost-control plan.

A full 76-channel analysis requires explicit confirmation and substantial compute. It is not required for a demonstration of the verified release. Preserve Run #10 and Run #11; do not rerun or tune them for a presentation.

## Reproducibility

- Scientific freeze: tag m131-run11-evaluated.
- Predeclared B1 selection: tag m131-b1-channel13-predeclared.
- Run artifacts and database are local and must be backed up separately from the Git repository.
- No independently validated production or flight deployment is claimed.
