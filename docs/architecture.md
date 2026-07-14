# Architecture

## The shift: from inline defense to root-cause diagnostics

The predecessor system (`../Vajra_SIH`, reference only) was an **inline active-defense
firewall**: `Inspect Packet → Detect Threat → Block Source`. Its detection engines
(Kitsune online anomaly detection, ML models, Suricata) and ingestion pipelines are
valuable, but the objective has changed.

This system operates **above** the infrastructure as an **observability & root-cause
diagnostics platform**. It does not block traffic; it explains *why* a complex,
multi-component anomaly occurred:

```
Ingest Signals → Detect Anomalies → Map Dependencies → Correlate Cross-Layer Events
→ Infer Probable Root Cause → Explain Evidence & Missing Data → Recommend Next Steps
```

Existing detection components become **passive diagnostic signal producers** feeding a
central correlation/RCA engine, rather than triggers for mitigation.

## Runtime (this prototype)

Constrained to run natively (no heavy infra) while preserving the target design:

| Concern | Prototype | Production target |
|---|---|---|
| Event bus | in-process async bus (`core/events.py`) | Apache Kafka |
| Topology graph | NetworkX (`graph/topology.py`) | Neo4j |
| Incident ledger | SQLite (`db/store.py`) | PostgreSQL |
| Similar-incident retrieval | history match | Qdrant + Neo4j **GraphRAG** |
| Telemetry | dataset replay on a live clock | Prometheus + OpenTelemetry + Elasticsearch |
| RCA orchestration | direct engine | LangGraph multi-agent |
| Explanations | Gemini + deterministic fallback | Gemini 2.5 Pro |

Interfaces are stable across the swap: producers call `bus.publish`, topology exposes the
same traversal methods, and the RCA engine consumes normalized `Event`s regardless of the
underlying store.

## Data flow

```
UNSW-NB15 flows ─┐
NSL-KDD          ├─▶ ingestion adapters ─▶ normalized Events ─▶ in-proc bus
HDFS logs        │                                                   │
config monitor ──┘ (real git commits)                               ▼
                                              Isolation Forest + labels ─▶ anomalies
                                                                    │
                          topology (real IP graph) ────────────────┤
                                                                    ▼
                                    RCA engine: correlation window + causal scoring
                                        + tri-categorized evidence + recommendations
                                                                    │
                                     SQLite audit ◀────────────────┤
                                     Gemini explanation ◀───────────┤
                                                                    ▼
                                        FastAPI REST + Socket.IO ─▶ Next.js dashboard
```

## Causal scoring (decomposable)

Each hypothesis accrues named, additive components (see `rca/scoring.py`), capped at 100:

| Component | Points | Meaning |
|---|---|---|
| `config_change_within_5s` | +30 | a config change on/upstream of the node just before the anomaly |
| `direct_upstream_dependency` | +30 | a real dependency path supports propagation |
| `confirmed_*_match` | +30 | confirmed direct evidence (diff / signature / label match) |
| `matching_propagation_path` | +20 | upstream anomaly temporally precedes the downstream one |
| `historical_pattern_match` | +10 | a similar past incident exists |
| `independent_corroboration` | +10 | an independent supporting signal |

The score is shown in the UI so operators can see exactly **why** a hypothesis ranks where
it does — correlation is never silently promoted to causation.

## Live replay & real config changes

The datasets are historical; the platform **replays real records on the wall clock** so
that a **real git commit made now** aligns temporally with the streamed anomalies. This is
how the flagship incident is genuine end-to-end: a real config change, real UNSW attack
flows for the affected node, and real correlation logic — no fabricated events.
