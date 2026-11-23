# VYOM — Spacecraft Telemetry Intelligence & Anomaly Operations Platform

VYOM is an explainable telemetry intelligence product built around **ESA Anomaly Detection Benchmark — Mission 1**. It combines memory-bounded telemetry access, retrospective anomaly analysis, event evidence, scientific reporting, a grounded knowledge assistant and an operations-oriented React interface.

> **Boundary:** VYOM is research decision support. It is not flight-qualified, does not control a spacecraft and contains no spacecraft-command path.

## What is in this final distribution

- FastAPI backend and SQLite persistence.
- 76-channel ESA Mission 1 catalog and annotation APIs.
- Bounded Parquet telemetry sampling for the UI.
- Chronological **60/20/20** retrospective fitting protocol.
- Exact disk-backed median/MAD/validation quantile computation using SQLite order statistics.
- Quantization-aware temporal point and interval scoring.
- Deterministic bounded Isolation Forest comparator.
- Causal cadence tracking and timestamp-gap candidates.
- Event grouping that stays open across processing batches.
- Per-channel reports and persisted event evidence.
- Internal VYOM Knowledge assistant through Nebius (optional).
- Tavily Live Research mode kept separate from mission evidence (optional).
- Premium desktop-first React operations UI.
- Docker and native Windows run paths.

## Dataset and artifacts are intentionally NOT bundled

The ESA source dataset and the 5.47 GiB M1.2 Parquet store are large and remain local. Point this package at your existing directories:

```text
D:\Projects\VYOM\VYOM\data\esa_adb\mission1\ESA-Mission1
D:\Projects\VYOM\VYOM\artifacts\milestone12\telemetry
```

If you replace your current repository with this package, copy or keep the existing `data/` and `artifacts/` directories beside it.

## Windows setup

```powershell
cd D:\Projects\VYOM\VYOM\backend
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` so these point at your existing data:

```env
DATASET_DIR=../data/esa_adb/mission1/ESA-Mission1
TELEMETRY_STORE_DIR=../artifacts/milestone12/telemetry
ARTIFACT_DIR=../artifacts/final
```

Then:

```powershell
python -m pytest -q
python -m uvicorn app.main:app --reload
```

Second terminal:

```powershell
cd D:\Projects\VYOM\VYOM\frontend
npm install
npm run dev
```

Open:

- UI: `http://localhost:5173`
- API: `http://localhost:8000/docs`

## Intelligence providers

Optional `.env` settings:

```env
NEBIUS_BASE_URL=https://api.tokenfactory.nebius.com/v1/
NEBIUS_API_KEY=
NEBIUS_MODEL=
TAVILY_API_KEY=
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=VYOM
```

VYOM Knowledge uses only internal retrieved evidence. Live Research uses Tavily and is explicitly returned as external evidence.

## Full-mission analysis

The UI defaults to selected channels. A 76-channel retrospective run requires an explicit confirmation because it is compute-intensive and should not be confused with live/flight analysis.

API request:

```json
{
  "full_mission": true,
  "confirm_full": true,
  "batch_rows": 5000
}
```

The product writes reports under `ARTIFACT_DIR/run_XXXXX/` and event records into the database.

## Scientific interpretation

The product reports VYOM's one-to-one closed-overlap event metric. It does **not** claim equivalence to ESA's official corrected alarming precision or affiliation metric. Unannotated periods follow the benchmark nominal-complement convention where assumption-dependent precision/F1 are shown; that does not prove physical normality. `Target=NO` channels remain contextual/unlabelled and are never manufactured into supervised negative labels.

Read `docs/SCIENTIFIC_PROTOCOL.md` before presenting benchmark results.
