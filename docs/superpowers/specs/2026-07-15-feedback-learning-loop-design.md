# Feedback Learning Loop — Design Spec

**Date:** 2026-07-15
**Scope:** Part 2 of `causal_inference_and_feedback_design.md`. Part 1 (DoWhy/CausalNex
Bayesian engine) is intentionally **not** built — see the assessment note in that
discussion. This spec covers the Active Feedback Learning loop only.

## Goal

Let an operator mark a ranked RCA hypothesis **Correct** or **Wrong** from the incident
dashboard, persist that judgement, and have it deterministically (and safely) influence
the ranking of hypotheses in future incidents on the same/similar node — with an audit
trail and a Qdrant "vector memory" ledger for the demo narrative.

## Non-goals

- No Bayesian/DoWhy/CausalNex inference.
- Qdrant feedback is **write-only** for now (not queried by scoring). SQLite/Postgres
  drives the actual score adjustment.
- No changes to detection or ingestion.

## Data flow

```
Operator clicks ✓/✗ on a HypothesisCard
  → POST /api/incidents/{id}/feedback
    → store.save_feedback()   (Postgres rca_feedback table, upsert on flip)
    → store.audit()           (existing audit_log — satisfies "audit records feedback")
    → rag.index_feedback()    (Qdrant vajra_feedback collection — non-fatal, write-only)
Next incident built:
  pipeline._run_agents() → await store.feedback_boost_map()   (async, once)
    → AgentState["feedback_boosts"]
    → root_cause_node applies capped node→global boost, then RE-SORTS + RE-RANKS
```

## Storage — `db/store.py` (PostgreSQL / asyncpg)

> Note: the store is **PostgreSQL via asyncpg**, not SQLite. Postgres column types
> (`DOUBLE PRECISION`, `BOOLEAN`) apply.

New table:

```sql
CREATE TABLE IF NOT EXISTS rca_feedback (
    feedback_id     VARCHAR(50) PRIMARY KEY,
    incident_id     VARCHAR(50) NOT NULL,
    focal_node      VARCHAR(50),
    hypothesis_rank INTEGER NOT NULL,
    hypothesis_kind VARCHAR(40) NOT NULL,
    root_cause      TEXT,
    is_correct      BOOLEAN NOT NULL,
    actor           VARCHAR(50) NOT NULL,
    ts              DOUBLE PRECISION NOT NULL,
    UNIQUE (incident_id, hypothesis_rank, actor)
);
```

Methods:
- `save_feedback(entry)` — `INSERT … ON CONFLICT (incident_id, hypothesis_rank, actor)
  DO UPDATE SET is_correct=EXCLUDED.is_correct, hypothesis_kind=EXCLUDED.hypothesis_kind,
  root_cause=EXCLUDED.root_cause, ts=EXCLUDED.ts`. **Flip safety:** one row per
  (incident, rank, actor) — a changed vote overwrites, never appends.
- `list_feedback(incident_id)` — rows for the UI to restore button state on reload.
- `feedback_boost_map()` → `{"node_kind": {"<node>|<kind>": net}, "kind": {kind: net}}`
  where `net = SUM(CASE WHEN is_correct THEN 1 ELSE -1 END)`. Because of the UNIQUE
  constraint the SUM cannot double-count a flipped vote.

## Scoring — `rca/scoring.py`

- Constants: `W_FEEDBACK_STEP = 5`, `W_FEEDBACK_MAX = 15`.
- `feedback_boost_points(net: int) -> int` — returns `clamp(net * W_FEEDBACK_STEP,
  -W_FEEDBACK_MAX, +W_FEEDBACK_MAX)`. **Returns a clean int** (drives the
  `feedback_learned_boost` breakdown pill and keeps totals integer).
- `confidence_from_components(components: dict[str, int]) -> float` —
  `total = max(0, min(MAX_SCORE, sum(components.values())))`; returns
  `round(total / MAX_SCORE, 3)`, a **float in [0, 1]** (this is what `ConfidenceBar`
  consumes — confidence is not an integer).
- Fix latent bug: `ScoreBreakdown.total` now floors at 0
  (`max(0, min(MAX_SCORE, sum(...)))`) so a negative component can't yield negative
  confidence.

## Agent graph — `agents/state.py`, `agents/nodes.py`

- `AgentState` gains `feedback_boosts: dict[str, Any]`.
- In `root_cause_node`, **after** the existing GraphRAG `historical_pattern_match`
  boost block, for each hypothesis:
  - `net = node_kind.get(f"{focal_node}|{kind}")` if present **else** `kind.get(kind, 0)`
    (node-scoped, global fallback).
  - `pts = feedback_boost_points(net)`; if `pts`: set
    `h["score_breakdown"]["feedback_learned_boost"] = pts` and
    `h["confidence"] = confidence_from_components(h["score_breakdown"])`.
  - Then **re-sort** hypotheses by confidence desc and **re-assign `rank`** (1-based).
    This is the visible "learning" — a promoted hypothesis becomes the new #1.

## Pipeline — `pipeline.py`

- `_run_agents(node, related)` awaits `store.feedback_boost_map()` and sets
  `initial_state["feedback_boosts"]`. Both incident paths (`_maybe_incident`,
  `_inject_config_change_impl`) already route through `_run_agents`.

## RAG ledger — `rag/qdrant.py`

- `index_feedback(entry)` — ensure a `vajra_feedback` collection (768-dim, cosine),
  upsert one point: `vector = _stable_hash_embedding(focal_node + kind + root_cause)`,
  payload includes `is_correct`, `incident_id`, `actor`, `ts`. **Fully wrapped /
  non-fatal** — any Qdrant error is swallowed so feedback saving never breaks.
  Write-only for now (durable memory for future retrieval + demo narrative).

## API — `main.py`

- `FeedbackIn(BaseModel)`: `hypothesis_rank: int`, `hypothesis_kind: str`,
  `root_cause: str`, `is_correct: bool`, `actor: str = "operator"`.
- `POST /api/incidents/{incident_id}/feedback` — 404 if incident missing; enrich with
  `feedback_id` (uuid hex[:12]), `focal_node` (from stored incident), `ts`;
  `store.save_feedback`; `store.audit(..., "feedback", …)`; best-effort
  `rag.index_feedback` in a thread (non-fatal). Returns `{"ok": True}`.
- `GET /api/incidents/{incident_id}/feedback` — `store.list_feedback(...)`.

## Frontend

- Per `frontend/AGENTS.md`, read the relevant guide in `node_modules/next/dist/docs/`
  before writing component code.
- `lib/types.ts` — `Feedback` type.
- `lib/api.ts` — `submitFeedback(id, payload)`, `getFeedback(id)`.
- `components/IncidentDetail.tsx` — thread `incidentId` into `HypothesisCard`; add
  ✓ **Correct RCA** / ✗ **Wrong RCA** buttons with local state, hydrate from
  `getFeedback` on mount. Fix the score-breakdown pill to render sign correctly
  (`{v >= 0 ? "+" : ""}{v}`) so a negative `feedback_learned_boost` shows `−10`,
  not `+-10`.

## Testing — `backend/tests/test_feedback.py`

1. `feedback_boost_points` clamping: net −10..+10 → clamped [−15, +15]; net 3 → 15.
2. `confidence_from_components`: floors at 0, caps at 1.0, returns float.
3. `feedback_boost_map` aggregation math incl. a flipped vote (one row, net respects
   the overwrite).
4. Boost application + re-rank: 3 "correct" votes for a rank-2 `config_change`
   hypothesis promotes it to #1.

## Safety properties

- Boost capped at ±15/100 — never overturns strong confirmed evidence.
- Confidence floored at 0, capped at 1.
- Qdrant indexing non-fatal.
- Votes idempotent via UNIQUE constraint (flip overwrites, no double-count).
- No new heavy dependencies.
