# Vajra RCA — Demo Runbook

Step-by-step guide for running the complete system and demonstrating it to judges.

---

## Prerequisites

| Tool | Version |
|---|---|
| Docker Desktop | ≥ 4.25 |
| Python | 3.12 |
| Node.js | ≥ 20 |
| `git` | any |

Datasets are pre-downloaded at `../datasets/` (UNSW_NB15, KDDTrain+, HDFS).

---

## Step 1 — Start Infrastructure

```bash
cd vajra-rca
docker compose up -d
```

Wait until all services are healthy (≈60 seconds):

```bash
docker compose ps
# All should show "healthy"
```

Services started:
| Service | URL |
|---|---|
| PostgreSQL | localhost:5432 |
| Neo4j | http://localhost:7474 |
| Qdrant | http://localhost:6333 |
| Kafka | localhost:9092 |
| Elasticsearch | http://localhost:9200 |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3001 |
| MinIO | http://localhost:9001 |

---

## Step 2 — Start the Backend

```bash
cd vajra-rca/backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Set environment (copy from .env.example if not already set)
cp .env.example .env
# Edit .env to set VAJRA_GOOGLE_API_KEY if you have one (optional)

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

On startup the backend will:
1. Connect to Postgres, Qdrant, Kafka
2. Load UNSW-NB15 dataset (20,000 rows) and fit Isolation Forest
3. Load HDFS log structured CSV (2,000 entries)
4. Build Neo4j topology from UNSW IP flows
5. Seed Qdrant with 4 SOP runbooks
6. Initialise Kitsune online detector

Wait for: `✓ Backend ready: flows_loaded=20000, topology=...`

---

## Step 3 — Start the Frontend

```bash
cd vajra-rca/frontend
npm install
npm run dev
```

Open: **http://localhost:3000**

Login: `admin` / `admin`

---

## Step 4 — Start Live Telemetry Replay

In the dashboard header, click **"Start Replay"** (or call the API):

```bash
curl -X POST http://localhost:8000/api/telemetry/replay/toggle \
     -H 'Content-Type: application/json' \
     -d '{"active": true}'
```

You will see:
- **Flows/s** counter incrementing (UNSW-NB15 at 30 events/s)
- **Alerts** counter incrementing (real attack labels from UNSW)
- **Kitsune** warmup: first 1000 packets are training — after ~33s, online anomaly detection starts
- Live Recharts graph updating every 15 events

---

## Step 5 — Trigger a Fault (Config Change Injection)

Click **"Inject Config Change"** or:

```bash
curl -X POST http://localhost:8000/api/inject/config-change \
     -H 'Content-Type: application/json' \
     -d '{}'
```

What happens (all real):
1. A **real git commit** is made to the config repo (`routing.yaml`)
2. A `ConfigChangeEvent` is published to Kafka
3. Real UNSW malicious flows for the focal node are streamed
4. **LangGraph 8-agent pipeline** runs:
   - Coordinator → Metric → Log → Trace → Graph → RAG → RootCause → Report
5. **Incident created** with:
   - Ranked root-cause hypotheses (config change ranked #1)
   - Decomposable confidence score (+30 config, +30 anomaly, +20 dependency, +10 historical)
   - Tri-classified evidence (Confirmed / Correlated / Missing)
   - Blast radius from Neo4j
   - Timeline
   - GraphRAG runbook recommendations

---

## Step 6 — Explore the Incident

1. Click on the incident in the **Incident List**
2. See the **Score Breakdown** chips (config_change: 30, anomaly_correlation: 30, ...)
3. Check the **Tri-Evidence Panel** (Confirmed/Correlated/Missing)
4. Click **"Explain"** → Gemini synthesises a narrative (or deterministic fallback)
5. Click **"Similar Runbooks"** → GraphRAG topology-aware matches
6. Use **AI Chat** to ask questions: `"Why is this ranked as a config change?"`
7. Click **"Generate Report"** → PDF uploaded to MinIO

---

## Step 7 — View Grafana

Open: **http://localhost:3001**

- Navigate to **Dashboards → Vajra → Vajra RCA Overview**
- Dashboard auto-loads with Prometheus datasource
- Shows: CPU, memory, HTTP request rate panels

---

## Step 8 — Check Detector Status

```bash
curl http://localhost:8000/api/detectors/status | jq
```

Expected output:
```json
{
  "kitsune":           {"enabled": true, "packet_count": 1500, "warmed_up": true, ...},
  "isolation_forest":  {"fitted": true},
  "hdfs_log_replay":   {"enabled": true, "events": 2000}
}
```

---

## Step 9 — Run E2E Verification

```bash
python scripts/verify_e2e.py http://localhost:8000
```

Expected: `ALL CHECKS PASSED ✅`

---

## Step 10 — Run Dataset Validation

```bash
python scripts/dataset_validation.py --datasets-dir ../datasets
```

This will fit Isolation Forest on real UNSW-NB15 and NSL-KDD test sets and output
real precision/recall/F1 to `docs/validation_results.md`.

---

## Topology View

The **Topology** tab shows a live React Flow graph of real IP-to-IP communication
derived from UNSW-NB15. The **hot node** (most-attacked destination) is highlighted.
After a config change injection, the blast radius nodes are highlighted in red.

---

## Architecture Summary

```
UNSW-NB15 CSV ──┐
HDFS Logs      ──┤──► Kafka EventBus ──► 8-Agent LangGraph ──► RCA Engine ──► Postgres
Kitsune Online ──┤                                  │                          │
Vajra ML .pkl  ──┤                              Neo4j / Qdrant              Socket.IO
Git Config     ──┘                                                          Frontend
```

All signal sources are real dataset records or real system events. Zero mocks.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Backend can't connect to Postgres | `docker compose up postgres -d` and wait for healthy |
| Neo4j connection refused | `docker compose up neo4j -d` — it takes ~30s |
| Qdrant not ready | `docker compose up qdrant -d` |
| Kitsune not detecting | Wait 33 seconds for warmup (1000 packets at 30/s) |
| Grafana shows no data | Prometheus scrape target: check `http://localhost:9090/targets` |
| Gemini fallback used | Set `VAJRA_GOOGLE_API_KEY` in `.env` — deterministic fallback still works |
| ML models not loading | Check `Vajra_SIH/ml_models/` exists relative to repo root |
