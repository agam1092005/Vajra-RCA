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

## Runtime (current)

The prototype now runs on the full target infra via `docker compose up -d`
(`docker-compose.yml`): Postgres, Neo4j, Qdrant, Kafka, Elasticsearch, Prometheus,
OTel-collector, Grafana, MinIO. The backend will not start without Postgres and
Neo4j reachable — `db/store.py` and `graph/topology.py` retry for ~30s then raise.

| Concern | Implementation |
|---|---|
| Event bus | `core/events.py` — publishes to Kafka; degrades to in-memory pub/sub if Kafka is unreachable |
| Topology graph | Neo4j (`graph/topology.py`), built from real observed UNSW IP communication |
| Incident ledger | PostgreSQL (`db/store.py`), async via `asyncpg` |
| Similar-incident / runbook retrieval | Qdrant + Neo4j **GraphRAG** (`rag/graphrag.py`, `rag/qdrant.py`) |
| Vector embeddings | a stable local hash function — deliberately not a live LLM call, since retrieval sits on the incident hot path (see `rag/qdrant.py`) |
| Telemetry | dataset replay on a live clock |
| RCA orchestration | LangGraph 8-agent pipeline (`agents/graph.py`): Coordinator → Metric → Log → Trace → Graph → RAG → RootCause → Report, streamed node-by-node so the UI can show live progress |
| Explanations | deterministic template inline on the incident-creation path; Gemini narrative generated on demand via `POST /api/incidents/{id}/explain` (never blocks incident creation) |
| Reports | PDF generated on demand and uploaded to MinIO (`utils/reporter.py`) |

Disk note: the full Docker image set (Postgres, Neo4j, Qdrant, Kafka, Elasticsearch,
Prometheus, Grafana, MinIO) needs several GB beyond the ~24GB datasets already on
disk — check free space before `docker compose up -d` if disk is constrained.

## Data flow

```
UNSW-NB15 flows ─┐
NSL-KDD          ├─▶ ingestion adapters ─▶ normalized Events ─▶ Kafka event bus
HDFS logs        │                                                   │
config monitor ──┘ (real git commits)                               ▼
                                     Isolation Forest + Kitsune + labels ─▶ anomalies
                                                                    │
                       topology (real IP graph, Neo4j) ────────────┤
                                                                    ▼
                            LangGraph 8-agent pipeline: correlation window + causal
                            scoring + tri-categorized evidence + GraphRAG runbooks
                                                                    │
                                Postgres audit ◀────────────────────┤
                        deterministic explanation (fast) ◀──────────┤
                                                                    ▼
                                        FastAPI REST + Socket.IO ─▶ Next.js dashboard
                                                                    │
                        Gemini narrative (on demand, via /explain) ┘
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
