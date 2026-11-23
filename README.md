# VYOM — Telemetry Intelligence

ESA Anomaly Detection Benchmark Mission 1 intelligence engine with a FastAPI backend, SQLAlchemy persistence and the existing React dashboard.

Milestone 1 now provides strict read-only source profiling, resumable Parquet ingestion, causal cadence-aware features, bounded statistical/Isolation Forest detection, timestamp-gap candidates, annotated events, chronological evaluation and reproducible manifests. PCA and supervised RF are available as explicit experimental APIs.

Start with [the implementation and execution guide](docs/MILESTONE1.md), [the complete dataset profile](docs/DATASET_PROFILE.md) and [measured pilot results](docs/PILOT_RESULTS.md).

## Local setup

The existing working interpreter is `backend/.venv/Scripts/python.exe`. Preserve `backend/.env`; optional settings are documented in `.env.example`.

```powershell
Set-Location 'D:\Projects\VYOM\VYOM\backend'
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

In another terminal, use the existing frontend setup (`npm install`, then `npm run dev` from `frontend`). Dashboard: `http://localhost:5173`; API documentation: `http://localhost:8000/docs`.

The dashboard's existing full-analysis button explicitly launches all-channel processing. For a bounded pilot, use the CLI commands in the guide. Do not use the dashboard button just to test server health.

## Source and artifacts

Original ESA files remain unchanged at `data/esa_adb/mission1/ESA-Mission1`. New derived files go under `artifacts/`, outside the source tree. Run `python -m app.cli --help` from `backend` for `profile`, `ingest` and `evaluate`. Repeating an identical command resumes completed channels after integrity checks.

## Verified status

- 82 tests pass; `pip check` passes.
- All 76 source channels were profiled read-only (744,856,895 observations).
- Five representative channels were ingested; a bounded 100,000-row prefix analysis plus two 20,000-row annotation diagnostics succeeded.
- Full 76-channel ingestion and full benchmark evaluation have **not** been executed.
- Detector diagnostics showed substantial false alarms and a missed point annotation. No deployment-quality accuracy is claimed.

Knowledge retrieval, optional Nebius chat and Tavily research remain separate from telemetry evidence. No spacecraft commands or autonomous control are implemented. Docker configuration and the existing frontend design remain unchanged.
