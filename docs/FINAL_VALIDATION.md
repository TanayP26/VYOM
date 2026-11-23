# Final package validation

Validation performed in the ChatGPT artifact sandbox before packaging.

## Passed

- Python `compileall` across `backend/app`.
- 7/7 included backend tests.
- Exact odd/even order-statistic tests.
- Cross-batch event continuity and large-gap separation tests.
- FastAPI health-contract smoke test with missing local ESA data handled as `degraded`, not a crash.
- TypeScript structural compile using local React/Vite declaration shims because npm dependencies cannot be downloaded in this sandbox.
- Secret scan: no API key values are bundled.

## Not executable in the sandbox

The following large local inputs are intentionally excluded from GitHub and therefore were not present here:

- ESA Mission 1 raw dataset.
- M1.2 5.47 GiB Parquet telemetry store.
- Existing M1/M1.1/M1.2/M1.3 generated artifacts.

Consequently, this sandbox did **not** rerun the final 76-channel retrospective benchmark or build the real frontend with downloaded npm dependencies. Run `scripts/verify_windows.ps1` on the existing VYOM workstation after pointing `.env` at the local dataset/store.

## Required local acceptance before quoting final model results

1. Run the included backend tests and `pip check`.
2. Run `npm run build`.
3. Verify `/api/health` reports dataset + telemetry store `ok`.
4. Execute a selected-channel run and inspect report/event artifacts.
5. Only then execute the complete 76-channel retrospective run.
6. Quote metrics from the newly generated final-product reports, not from the earlier exposed diagnostic windows as if they were blind validation.
