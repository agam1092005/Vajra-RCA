# Design Document: Bayesian Causal Inference & Feedback Learning Loop

This design document outlines the step-by-step blueprint to upgrade the **Vajra RCA** platform from a rule-based temporal correlation engine to a **true Bayesian Causal Inference engine** using **DoWhy / CausalNex**, combined with an **Active Feedback Learning loop** that dynamically improves RAG-based RCA ranking based on operator input.

---

## 1. The Core Paradigm Shift: Correlation vs. Causation

Currently, the engine uses **temporal correlation** (e.g., config change and anomaly happened in the same 5-second window). However, this only tells us that **"A and B occurred together."** 

By integrating causal frameworks, we can prove **"A caused B"**:

```mermaid
graph TD
    subgraph Correlative View (Score: 4/10)
        C[Config Change] -. Same Window .- L[Packet Loss]
        A[Attack Traffic] -. Same Window .- L
    end

    subgraph Causal View (Score: 10/10)
        C_true[Config Change] -- do(C=1) --> L_true[Packet Loss]
        A_true[Attack Traffic] -- Confounder --> L_true
        style C_true fill:#22c55e,stroke:#15803d,stroke-width:2px
    end
```

### Key Differences
| Attribute | Correlative Model (Current) | Bayesian Causal Model (Proposed) |
| :--- | :--- | :--- |
| **Logic** | "We saw a config commit and packet loss within $t \pm 5s$." | "Intervening on the routing config table (setting $do(C=1)$) increases the probability of packet loss on Node X by 85%." |
| **Impact Rating** | ⭐ 4 / 10 | ⭐ 10 / 10 |
| **Handling of Confounders** | Treats concurrent DDoS alerts and config changes as competing correlation weights. | Blocks back-door pathways (confounders) using the physical topology DAG. |

---

## 2. Mathematical Integration

### Option A: Bayesian Networks (CausalNex)
We construct a **Conditional Probability Table (CPT)** at each node in the topology:

$$P(\text{Packet Loss} \mid \text{Config Change}, \text{Attack Traffic}, \text{Upstream Failure})$$

Using CausalNex, we train the parameters of the Bayesian Network using historical logs and continuous telemetry replays. When a new incident occurs, we query the posterior probability:

$$P(\text{Config Change} = \text{True} \mid \text{Packet Loss} = \text{True})$$

### Option B: DoWhy Causal Inference
DoWhy uses structural causal models to execute 4 steps:
1. **Model**: Define the DAG structure using the NetworkX `TopologyGraph`.
2. **Identify**: Find the causal estimand (e.g., blocking the path of external network traffic to isolate internal config change impact).
3. **Estimate**: Estimate the causal effect (e.g., using linear regression or propensity score matching).
4. **Refute**: Run robustness tests (e.g., replacing the config change with a random placebo variable to verify the effect drops to zero).

---

## 3. Feedback Learning Loop Architecture

To continuously align the system with actual operator outcomes, we introduce an **Active feedback ledger**:

```mermaid
sequenceDiagram
    autonumber
    actor Engineer
    participant UI as Next.js Dashboard
    participant API as FastAPI Backend
    participant DB as SQLite / Postgres
    participant RAG as Qdrant Vector DB

    Engineer->>UI: Clicks "Correct RCA" or "Wrong RCA"
    UI->>API: POST /api/incidents/{id}/feedback
    API->>DB: Save feedback entry to rca_feedback table
    API->>RAG: Embed incident characteristics + feedback label
    Note over RAG: Future incidents query Qdrant;<br/>similar past incidents with "Correct RCA"<br/>boost corresponding hypothesis kinds.
```

---

## 4. Implementation Steps

### Step 1: Database Migration
We create the feedback ledger table in `backend/app/db/store.py`.

```sql
CREATE TABLE IF NOT EXISTS rca_feedback (
    feedback_id VARCHAR(50) PRIMARY KEY,
    incident_id VARCHAR(50) NOT NULL,
    hypothesis_rank INTEGER NOT NULL,
    hypothesis_kind VARCHAR(30) NOT NULL,
    root_cause TEXT NOT NULL,
    is_correct BOOLEAN NOT NULL,
    actor VARCHAR(50) NOT NULL,
    timestamp DOUBLE PRECISION NOT NULL,
    FOREIGN KEY(incident_id) REFERENCES incidents(incident_id)
);
```

### Step 2: FastAPI API Integration
Add the feedback endpoint in `backend/app/main.py`:

```python
class FeedbackIn(BaseModel):
    hypothesis_rank: int
    hypothesis_kind: str
    root_cause: str
    is_correct: bool
    actor: str = "operator"

@api.post("/api/incidents/{incident_id}/feedback")
async def save_feedback(incident_id: str, body: FeedbackIn) -> dict:
    feedback_entry = {
        "feedback_id": uuid.uuid4().hex[:12],
        "incident_id": incident_id,
        "hypothesis_rank": body.hypothesis_rank,
        "hypothesis_kind": body.hypothesis_kind,
        "root_cause": body.root_cause,
        "is_correct": body.is_correct,
        "actor": body.actor,
        "timestamp": time.time()
    }
    await store.save_feedback(feedback_entry)
    
    # Optional: Update Qdrant vector memory
    await rag.index_feedback_event(incident_id, feedback_entry)
    
    return {"status": "success"}
```

### Step 3: Dynamic RAG Scoring & Rank Boosting
Update the RAG engine in `backend/app/rag/qdrant.py` and `backend/app/rca/engine.py` to retrieve past confirmed root causes.

When building hypotheses, query Qdrant for similar incidents:
1. Retrieve top 5 most similar past incidents.
2. Filter for those marked with `is_correct = True`.
3. If a past incident on the same/similar node has a confirmed `hypothesis_kind` matching the current candidate, boost the score dynamically:

```python
# In backend/app/rca/engine.py
similar_sops = rag.search_sops(focal_node_signature, limit=3)
feedback_boost = store.get_feedback_boost_for_kind(hypothesis_kind) # e.g., config_change -> +15 points
sb.add("feedback_learned_boost", feedback_boost)
```

### Step 4: Frontend UI Integration
Add feedback buttons directly inside the `HypothesisCard` component in `frontend/src/components/IncidentDetail.tsx`:

```tsx
// Inside HypothesisCard render
const [feedback, setFeedback] = useState<'correct' | 'wrong' | null>(null);

const handleFeedback = async (isCorrect: boolean) => {
  try {
    await api.submitFeedback(incidentId, {
      hypothesis_rank: h.rank,
      hypothesis_kind: h.kind,
      root_cause: h.root_cause,
      is_correct: isCorrect
    });
    setFeedback(isCorrect ? 'correct' : 'wrong');
  } catch (err) {
    console.error("Feedback submit failed", err);
  }
};
```

Render visually intuitive indicators:
- **Correct RCA** (Green Checkmark Button)
- **Wrong RCA** (Red Cross Button)

---

## 5. Verification Plan

### Automated Tests
1. **API Validation**: Write integration tests asserting that posting a feedback payload returns 200 and successfully commits to SQLite/Postgres.
2. **Scoring Logic**: Inject mock feedback (e.g. marking `config_change` as the correct RCA 10 times), trigger pipeline replay, and assert that the `config_change` hypothesis confidence increases dynamically.

### Manual Verification
1. Navigate to the incident dashboard.
2. Click on the flagship incident.
3. Click "Correct RCA" on Hypothesis #1 (Config change).
4. Verify the audit log records the feedback action.
5. Re-run or inject another config change anomaly and verify that the confidence score is boosted by feedback history.
