# Full cloud deployment — VYOM v2.0.0 extension

The v2.0.0 tag and native installation remain unchanged. This separate branch packages the full React application and FastAPI API into one same-origin service. It runs one API worker, persists its SQLite database and artifacts on a Railway volume, and retains the statistical detector unchanged.

## Status and prerequisites

The VYOM Railway project and empty service were provisioned. The initial persistent-volume request failed because the workspace's current plan permits only 5,000 MB. The Parquet store alone is approximately 5.47 GiB. No public endpoint or running deployment has been established. Do not start a full mission run to populate the cloud.

A larger persistent volume is required. The Railway subscription upgrade must be performed by the account owner. Measure the complete dataset, telemetry and archived run evidence before sizing the volume. Reserve additional space for future analyses; the cloud request guard requires 2 GiB per requested channel plus 2 GiB free space, a conservative operational estimate, not a measured upper bound. A 76-channel run therefore requires at least 154 GiB free under this guard. Reassess actual storage and cost before execution. A larger volume does not validate full-mission detection.

## 1. Verify and snapshot on Windows

Stop the native application cleanly, ensure no queued/running analyses, and use a NEW snapshot directory outside the repository on a drive with adequate free space.

```powershell
cd D:\Projects\VYOM\VYOM
git fetch origin
git switch --track origin/cloud-full-deployment
.\scripts\verify_windows.ps1
cd D:\Projects\VYOM\VYOM\backend
.\.venv\Scripts\python.exe -m pytest ..\cloud\test_entry.py -q
.\.venv\Scripts\python.exe ..\cloud\migrate.py prepare D:\VYOM_cloud_snapshot
```

The script copies the original dataset, 76-channel Parquet store and archived final reports, then backs up SQLite using its backup API. It checks all channel row counts, 3,589 annotations, historical Run 10/11 counts and SQLite integrity, and records SHA-256 for each file. Review the snapshot for confidential content before upload. Never commit it or the local .env. Failed preparation leaves a partial directory; preserve/inspect it and use a new directory for a retry.

## 2. Provision and deploy in import mode

Use a volume of adequate capacity mounted at /vyom-data. Set VYOM_CLOUD_MODE=import. This mode exposes only a shallow health endpoint and does not open or initialize the SQLite database. Configure Dockerfile.cloud at repository root and the healthcheck /cloud-health. Use a single replica and worker. Deploy the cloud-full-deployment branch. Do not expose a public domain yet.

## 3. Upload and verify

Use Railway CLI volume file upload or the authenticated SFTP interface. Upload the CONTENTS of the prepared snapshot to the mounted volume root so that /vyom-data/dataset, /vyom-data/telemetry, /vyom-data/reports, /vyom-data/vyom.db and /vyom-data/migration_inventory.json exist. Do not overwrite an existing accepted database or copy .env.

Inside the import-mode service, run:

```sh
python /app/cloud/migrate.py verify /vyom-data --mark-ready
```

The verifier must report 76 channels, 744856895 observations, Run 10 = 31308 incidents and Run 11 = 7747 incidents. All uploaded files must match the inventory. Archived Windows paths in existing report metadata are historical provenance; the cloud telemetry reader locates the files using its existing filename fallback. No archive is rewritten. Historical failed runs and abstentions are retained.

## 4. Configure credentials and serve

In Railway Variables (never in Git or a chat message), set a new shared research-workspace username and a random password of at least 24 characters using VYOM_CLOUD_USER and VYOM_CLOUD_PASSWORD. Set NEBIUS_API_KEY, NEBIUS_MODEL (the exact provider catalog identifier), NEBIUS_BASE_URL, TAVILY_API_KEY, LANGSMITH_API_KEY and LANGSMITH_PROJECT as needed. Do not copy API_KEY unless separately implementing the native x-vyom-key frontend flow; the cloud gate authenticates the whole workspace. Use HTTPS on the generated Railway domain; set VYOM_CLOUD_MODE=serve only after verification. Browser authentication is HTTP Basic on HTTPS, appropriate for this small trusted academic group but not a multi-tenant production identity system.

The gate blocks cross-origin POSTs, remote knowledge ingestion, oversized bodies, repeated inference/research calls and analysis launches lacking disk headroom. It is process-local and not a persistent spending quota. Set Railway usage limits and provider-side budgets as well. No public anonymous access. Keep deployment at one replica; redeployments interrupt active runs. Do not redeploy during analysis.

## 5. Acceptance

Verify the service deployment reaches SUCCESS, unauthenticated requests are rejected, and the authenticated frontend loads. Check mission summary, all 76 channels, Run 10/11 counts, telemetry on multiple channels, report details and assistant/research traces. Confirm the actual cloud runtime has access to the complete data and verify persistence across a controlled restart without any analysis running. New detector runs are separate from the historical evidence and must be explicitly requested. A cloud-hosted research application is not a flight-qualified system.

The cloud-specific code is not yet regression-tested or runtime-verified. The original local 293-test result is not proof that this extension works. Keep the verified native installation and video available for the presentation.
