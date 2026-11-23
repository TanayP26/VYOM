# VYOM final architecture

```text
ESA Mission 1 source metadata            M1.2 Parquet telemetry store
        |                                          |
        +-------------------+----------------------+
                            v
                   FastAPI product layer
                   /        |         \
          catalog/query   analysis    intelligence
              |              |             |
       bounded Arrow     60/20/20      internal docs
       telemetry reads   retrospective  + Nebius
                          protocol       + Tavily (external)
                              |
                exact disk-backed calibration
                              |
       temporal point / interval / IF / gap candidates
                              |
                causal event aggregation
                              |
            evidence + SQLite persistence
                              |
                    React operations UI
```

## Product surfaces

- Overview: mission coverage, annotations, event burden and run state.
- Mission Monitor: safe selected-channel execution and explicit full-run control.
- Telemetry Explorer: bounded downsampled channel views.
- Event Intelligence: persisted event evidence and annotation correlation.
- Model Lab: frozen protocol and model semantics.
- Knowledge Assistant: internal evidence vs separately labelled external research.
- Reports: per-channel machine-readable analysis reports.
- System Health: data/provider checks and scientific disclosures.

## Operational boundaries

VYOM reads local benchmark telemetry. It does not transmit spacecraft commands, rewrite ESA source files or imply that an anomaly score is a probability of failure.
