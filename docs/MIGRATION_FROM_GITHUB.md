# Migration from TanayP26/VYOM

This distribution consolidates the product surface around the scientific principles established in M1–M1.3. Keep your existing large local folders:

- `data/esa_adb/mission1/ESA-Mission1`
- `artifacts/milestone12/telemetry`

Before replacing code, keep a Git branch/tag of the milestone repository. The historical M1/M1.1/M1.2/M1.3 research files remain valuable audit evidence even when the final product code is used for the demonstration.

Recommended workflow:

```powershell
git checkout -b milestone-archive
# preserve current milestone source

git checkout main
# copy final distribution source over the working tree, excluding data/artifacts
```

Do not delete the M1.2 telemetry store; the final product reads it directly.
