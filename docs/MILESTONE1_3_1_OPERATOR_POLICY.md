# VYOM M1.3.1 — Temporal-first operator incident policy

## Active decision

The operator-facing `combined` stream is now:

```text
combined_flag = temporal_point_flag OR persistent_temporal_interval_flag
```

Isolation Forest remains available as an independent scientific comparator and
supporting signal, but it cannot independently create an operator incident.

No point threshold, interval threshold, validation quantile, persistence rule,
cadence rule, feature definition, chronological split, or event-grouping rule
is changed by this patch.

## Why

The development-exposed M1.1 diagnostics already showed that temporal detection
carried the supported CH-12 interval and CH-61 point detections, while adding
Isolation Forest could substantially increase burden (notably CH-74). This is
the selection basis for the temporal-first operator policy.

Run #10 B was subsequently used only to diagnose the old M1.3.0 mechanism. Its
sample-level attribution showed 25,546 combined flags created by the
Isolation-Forest + half-temporal-threshold path despite no temporal flag. No
threshold is selected from Run #10.

## Preserved baseline

The exact M1.3.0 rule remains documented and reproducible for diagnostics:

```text
temporal_flag OR (isolation_forest_flag AND temporal_ratio > 0.5)
```

Run #10 artifacts remain the frozen M1.3.0 baseline and must not be overwritten.

## Validation boundary

The next scientific evaluation should use one predeclared, previously
unexposed B1 `Target=YES` channel. Freeze M1.3.1 before viewing that channel's
predictions or labels. Do not launch the 76-channel benchmark until that
single-channel result, burden, runtime and integrity are reviewed.

This remains retrospective research decision support, not external blind
validation or flight-qualified anomaly detection.
