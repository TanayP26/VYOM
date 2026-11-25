# Release deployment checklist

## Verified native baseline

The Windows release candidate passed 293 backend tests, dependency checks and the frontend production build. The existing native installation is the recommended demonstration path because its database contains the historical runs. Local container startup and HTTP/provider smoke tests were subsequently verified on Windows Docker Desktop. See the observed deployment acceptance record below.

Stop VYOM before backing up its local SQLite database and run artifacts. Preserve the source dataset, Parquet store, Run 10 and Run 11 artifacts, and database independently of Git. Never copy secrets into the repository or presentation.

## Local container demonstration

The Compose configuration is intentionally loopback-only. It mounts the existing ESA dataset, Parquet store and documentation read-only; the container has a separate named volume for its database and new artifacts. It does not import or overwrite the native Windows run database.

Requirements: Docker Desktop with Compose, an existing ESA dataset and M1.2 Parquet store in the paths defined by Compose, sufficient disk space, and a local backend/.env file. Optional provider credentials remain in that file, not in image layers.

Stop the native VYOM processes to release ports 8000 and 5173. From the repository root:

```powershell
docker compose config --quiet
docker compose up --build -d
docker compose ps
Invoke-RestMethod http://localhost:8000/api/health
Invoke-RestMethod http://localhost:8000/api/system/health | ConvertTo-Json -Depth 8
Invoke-RestMethod http://localhost:8000/api/mission/summary | ConvertTo-Json -Depth 8
```

Open http://localhost:5173 and inspect the mission summary and a telemetry sample. Test the assistant with a documented scientific question if Nebius is configured. Verify that the returned sources contain the current scientific protocol and B1 evaluation.

A new container database has no historical run rows. This is expected: do not execute a new benchmark solely to populate the demonstration, and do not copy a live database into the container. For the assessed Run 10/11 demonstration, use the existing native installation. Migration of native evidence into an isolated database needs a separate, explicit procedure with path reconciliation and integrity verification.

```powershell
docker compose logs --tail 100 api web
docker compose down
```

Do not use `docker compose down -v` unless intentionally discarding the isolated container runtime. If an older container image was built before the credential exclusions were added, inspect its distribution history; rotate credentials if such an image was shared or published.

## Public deployment boundary

This configuration is not a public hosting architecture. The current API exposes read endpoints and optional inference; its in-process run lock assumes one worker. Before exposing it beyond localhost, require application-level authentication and authorization, rate limits and inference budgets, protected artifacts, HTTPS, audited secret handling, persistent storage and worker coordination. No public hosting or production validation is claimed.

## Release acceptance

- Native regression script passes on the final checkout.
- All eight views are inspected using the actual dataset.
- Existing Run 10/11 records and reports remain accessible in the native installation.
- Nebius returns a grounded answer; LangSmith tracing is checked separately if configured.
- Container startup and its health/mission APIs are verified before calling the container deployment complete.
- Report, presentation and README state the observed detection limitations and the absence of full-mission modeling and flight validation.

## Observed deployment acceptance — 25 November 2026 (IST)

The local Docker Compose build and startup succeeded with Docker Engine 29.9.3 and Compose 5.7.0. Both images built; the API was healthy and the web service running on loopback ports 8000 and 5173. The persistent runtime volume was created.

- Frontend HTTP response: 200.
- Dataset and Parquet store checks: successful; 76 ingested channels, 744,856,895 observations, 3,589 annotations.
- CH-13 telemetry: 1,400 returned points from a bounded 28,000-row prefix of 14,258,506 source rows (2000-01-01 to 2000-01-30 UTC).
- Nebius: successful response to a Run 11 scientific question, including six retrieved internal documents and the current evaluation record.
- Tavily: six external research results, explicitly separated from internal mission evidence.
- LangSmith: configured, actual trace verification pending.
- Persistence across container recreation, all-page browser acceptance, and public deployment were not independently demonstrated by these smoke tests.

The assistant response correctly reported the missed annotation, unknown physical truth of unmatched candidates, and unavailable supported precision/F1, but overstated cross-channel comparison and event dependence. Subsequent prompt clarification requires a fresh inference smoke test; it does not change scientific scoring. This record describes the observed packaging smoke tests, not a fresh scientific evaluation.
