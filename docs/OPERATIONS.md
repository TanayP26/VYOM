# Operations guide

## Safe first launch

1. Start the backend.
2. Open `/api/health` and verify dataset + telemetry store are `ok`.
3. Start the frontend.
4. Use Mission Monitor with three representative channels first.
5. Inspect `artifacts/final/run_XXXXX/<channel>/report.json` and event burden.
6. Only then authorize a full 76-channel retrospective run.

## Troubleshooting

- `Dataset not found`: set `DATASET_DIR` to the folder containing `channels.csv`.
- `Telemetry Parquet store not found`: set `TELEMETRY_STORE_DIR` to the M1.2 store containing `manifest.json`.
- Assistant says Nebius is not configured: set `NEBIUS_API_KEY` and `NEBIUS_MODEL`.
- Live Research empty: set `TAVILY_API_KEY`.
- High event burden: do not tune on final test labels. Inspect calibration and channel regime behaviour first.

## Database reset

The SQLite database contains product runs/events/knowledge documents only. To reset local UI state, stop the backend and remove `backend/vyom.db`. This does not touch ESA data or Parquet telemetry.
