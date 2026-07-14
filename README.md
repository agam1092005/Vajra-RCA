# Vajra RCA — Network Anomaly Root-Cause Assistant

An explainable, evidence-backed **root-cause analysis platform** for network and
infrastructure anomalies. It ingests heterogeneous real signals (network telemetry,
system logs, security alerts, topology, configuration changes), detects anomalies,
and produces **ranked root-cause hypotheses** that separate **correlation from
causation** — each with a decomposable confidence score, tri-categorized evidence
(Confirmed / Correlated / Missing), an incident timeline, risk-tiered remediation
recommendations, and a non-repudiable audit trail.

> Challenge 02 — Network Anomaly Root-Cause Assistant. Built on **real datasets**
> (NSL-KDD, UNSW-NB15, HDFS logs) and **real configuration changes** (a live git
> repository). No mock data, no hardcoded verdicts — every signal is genuine and every
> hypothesis is derived at runtime.

---

## What it does

| Requirement | How it is met |
|---|---|
| Ingest telemetry, logs, alerts, topology, config changes | Adapters for UNSW-NB15 flows (real IPs/ports/timestamps), NSL-KDD, HDFS logs, and a git-backed config-change monitor |
| Detect anomalies across time windows | Isolation Forest (scikit-learn) fit on real baselines + a 5-minute correlation window |
| Correlate signals, avoid time-based blame | Deterministic causal scoring using the real dependency graph + temporal ordering |
| Use topology / dependency data | NetworkX dependency graph built from real observed IP communication; upstream/downstream/blast-radius traversal |
| Ranked root-cause hypotheses w/ evidence | `RCAEngine` produces ranked hypotheses, each with a decomposable score breakdown |
| Separate Confirmed / Correlated / Missing evidence | First-class tri-categorized evidence classifier |
| Incident timeline | Synchronized, multi-source chronological timeline per incident |
| Recommend next steps + auditable trail | Risk-tiered recommendations (diagnostic / low-risk / high-impact) + SQLite audit ledger |

The intellectual core is the **Correlation & Causal Inference engine**: it moves beyond
"these happened at the same time" by weighting a config change's timing, the real
dependency path between components, anomaly propagation order, historical patterns, and
independent corroboration — producing a transparent Causal Confidence Score out of 100.

---

## Architecture

```
 Real sources ─────────────────────────────────────────────┐
   • UNSW-NB15 flows (telemetry + security alerts + IPs)    │
   • NSL-KDD (labelled traffic, detector training/validation)│
   • HDFS logs (+ block-level anomaly ground truth)          ├─▶ Event Bus ─▶ Detection ─▶ RCA Engine ─▶ API + Socket.IO ─▶ Dashboard
   • Config-change monitor (real git repo: actor/diff/time)  │      (in-proc)   (Isolation   (topology +      (FastAPI)         (Next.js)
                                                              │                  Forest)     causal scoring
 Live replay puts real records on the wall clock ────────────┘                              + evidence)
```

- **Backend** — FastAPI + Socket.IO, Python 3.12. Ingestion, Isolation Forest detection,
  NetworkX topology, the causal RCA engine, Gemini explanations (optional), SQLite audit.
- **Frontend** — Next.js + Tailwind + React Flow (topology) + Recharts (live metrics),
  live-updating over Socket.IO.

See [`docs/architecture.md`](docs/architecture.md) and [`docs/system-features.md`](docs/system-features.md).

---

## Prerequisites

- **Python 3.12** (the host default 3.14 lacks some ML wheels; this repo pins 3.12)
- **Node.js 20+** and npm
- [`uv`](https://github.com/astral-sh/uv) (fast Python env/installer) — optional but recommended
- The datasets, placed at `../datasets` relative to this project (see below)
- *(Optional)* a Google Gemini API key for natural-language explanations & chat

### Datasets layout

The platform reads real files from `../datasets` (kept outside the repo; ~24 GB):

```
datasets/
├── KDDTrain+/KDDTrain+.txt              # NSL-KDD (committed with the challenge)
├── UNSW_NB15/UNSW-NB15_1..4.csv         # raw flows with real IPs/ports/timestamps
│   └── NUSW-NB15_features.csv           # column dictionary
└── HDFS/HDFS_2k/HDFS_2k.log_structured.csv
    └── ../HDFS_v1/preprocessed/anomaly_label.csv
```

Override the location with `VAJRA_DATASETS_DIR=/path/to/datasets`.

---

## Quick start

### 1. Backend

```bash
cd backend
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e .
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The API comes up on `http://localhost:8000`. On startup it loads real UNSW flows,
builds the topology, fits the detector, and begins live replay. Check readiness:

```bash
curl http://localhost:8000/api/health        # {"status":"ok","ready":true}
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev            # http://localhost:3000
```

Open **http://localhost:3000**. You'll see live signal rates, the dependency topology,
and incidents appearing in real time.

### 3. Trigger the flagship incident

Click **"Inject Config Change"** (or `POST /api/inject/config-change`). This makes a
**real git commit** to the monitored config repo, then correlates it against the real
anomalies streaming for the affected node — producing the canonical result:

> **#1 (high confidence)** — routing configuration change on the affected node, with
> confirmed evidence (the commit diff + dependency path + sub-5s timing), the concurrent
> attack traffic demoted to a **correlated** signal, and the missing telemetry called out.

### Optional: enable Gemini explanations

```bash
export VAJRA_GOOGLE_API_KEY=your_key       # backend picks it up
```

Without a key, explanations and chat fall back to a fully deterministic generator.

---

## Configuration

All settings are environment variables prefixed `VAJRA_` (see `backend/app/core/config.py`):

| Variable | Default | Purpose |
|---|---|---|
| `VAJRA_DATASETS_DIR` | `../datasets` | Location of the real datasets |
| `VAJRA_GOOGLE_API_KEY` | — | Gemini key (optional) |
| `VAJRA_CORRELATION_WINDOW_S` | `300` | Incident correlation window |
| `VAJRA_CONFIG_CAUSAL_WINDOW_S` | `5` | "config change within N s" causal bonus |
| `VAJRA_PORT` | `8000` | API port |

Frontend: `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`) in `frontend/.env.local`.

---

## API surface (selected)

| Method | Path | Description |
|---|---|---|
| GET | `/api/status` | pipeline + detector + topology summary |
| GET | `/api/metrics` | live signal counters/rates |
| GET | `/api/topology` | dependency graph for visualization |
| GET | `/api/incidents` | ranked incident list |
| GET | `/api/incidents/{id}` | full incident (hypotheses, evidence, timeline) |
| POST | `/api/incidents/{id}/explain` | natural-language explanation |
| POST | `/api/incidents/{id}/chat` | grounded Q&A about the incident |
| GET | `/api/incidents/{id}/audit` | audit trail |
| POST | `/api/inject/config-change` | make a real config change and correlate |

Socket.IO events: `metrics`, `incident`, `alert`, `anomaly`, `config_change`.

---

## Detection quality

The Isolation Forest is validated against the real UNSW-NB15 attack labels
(`backend/app/detection/isolation_forest.py::validate`) — labels are used only to
*measure* the unsupervised detector, never to drive detection. Run:

```bash
cd backend && .venv/bin/python -m scripts.validate_detector
```

---

## Project layout

```
vajra-rca/
├── backend/app/
│   ├── ingestion/   # unsw, nsl_kdd, hdfs, config_monitor
│   ├── detection/   # isolation_forest
│   ├── graph/       # topology (NetworkX)
│   ├── rca/         # scoring + engine (correlation & causal inference)
│   ├── llm/         # gemini (+ deterministic fallback)
│   ├── db/          # SQLite audit ledger
│   ├── core/        # config, events, serialization
│   ├── pipeline.py  # live replay orchestrator
│   └── main.py      # FastAPI + Socket.IO
├── frontend/        # Next.js dashboard
└── docs/            # architecture + system features
```

## Roadmap

The prototype runs natively with embedded backends (NetworkX, SQLite, in-process bus) to
stay light. The production path swaps these for the full stack without changing
interfaces: Neo4j (topology), Kafka (event bus), Postgres (ledger), Qdrant + GraphRAG
(similar-incident retrieval), Prometheus/OpenTelemetry/Elasticsearch (live telemetry),
and a LangGraph multi-agent RCA pipeline. See `docs/architecture.md`.
