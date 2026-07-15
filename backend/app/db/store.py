"""PostgreSQL-backed incident ledger + audit trail (the spec's 'Auditable Incident Trail').

Records incidents, their ranked hypotheses/evidence, generated recommendations,
human actions and resolution state — a non-repudiable, queryable history.
"""
from __future__ import annotations

import json
import time
import asyncio
import asyncpg
from typing import Any

from ..core.config import settings


def aggregate_feedback_rows(rows: list[dict]) -> dict:
    """Reduce raw rca_feedback rows into a net-vote boost map.

    net = Σ(is_correct ? +1 : -1) grouped by node+kind and, separately, by kind.
    Because the table has UNIQUE(incident_id, hypothesis_rank, actor), a flipped
    vote is a single overwritten row — this SUM cannot double-count it.

    Returns: {"node_kind": {"<node>|<kind>": net}, "kind": {"<kind>": net}}
    """
    node_kind: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    for r in rows:
        delta = 1 if r["is_correct"] else -1
        kind = r["hypothesis_kind"]
        node = r.get("focal_node") or ""
        node_kind[f"{node}|{kind}"] = node_kind.get(f"{node}|{kind}", 0) + delta
        by_kind[kind] = by_kind.get(kind, 0) + delta
    return {"node_kind": node_kind, "kind": by_kind}


class Store:
    def __init__(self) -> None:
        self.pool: asyncpg.Pool | None = None

    async def initialize(self) -> None:
        """Create connection pool and tables if they do not exist."""
        for attempt in range(15):
            try:
                self.pool = await asyncpg.create_pool(
                    settings.postgres_url,
                    min_size=2,
                    max_size=15
                )
                break
            except Exception as e:
                print(f"[Postgres] Connection attempt {attempt + 1}/15 failed: {e}")
                await asyncio.sleep(2)
        else:
            raise RuntimeError("[Postgres] Failed to connect to PostgreSQL container.")

        async with self.pool.acquire() as conn:
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS incidents (
                incident_id VARCHAR(50) PRIMARY KEY,
                focal_node  VARCHAR(50),
                title       TEXT,
                severity    VARCHAR(20),
                status      VARCHAR(20),
                detected_at DOUBLE PRECISION,
                window_start DOUBLE PRECISION,
                window_end   DOUBLE PRECISION,
                top_cause    TEXT,
                top_confidence DOUBLE PRECISION,
                data        TEXT
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                id SERIAL PRIMARY KEY,
                ts DOUBLE PRECISION,
                incident_id VARCHAR(50),
                actor VARCHAR(50),
                action VARCHAR(100),
                detail TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_incidents_detected ON incidents(detected_at DESC);
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
            CREATE INDEX IF NOT EXISTS idx_feedback_kind ON rca_feedback(hypothesis_kind);
            """)

    async def save_incident(self, incident: dict) -> None:
        if self.pool is None:
            raise RuntimeError("PostgreSQL store is not initialized")
        hyps = incident.get("hypotheses", [])
        top = hyps[0] if hyps else {}
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO incidents
                   (incident_id, focal_node, title, severity, status, detected_at,
                    window_start, window_end, top_cause, top_confidence, data)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                   ON CONFLICT (incident_id) DO UPDATE SET
                   focal_node=EXCLUDED.focal_node,
                   title=EXCLUDED.title,
                   severity=EXCLUDED.severity,
                   status=EXCLUDED.status,
                   detected_at=EXCLUDED.detected_at,
                   window_start=EXCLUDED.window_start,
                   window_end=EXCLUDED.window_end,
                   top_cause=EXCLUDED.top_cause,
                   top_confidence=EXCLUDED.top_confidence,
                   data=EXCLUDED.data""",
                incident["incident_id"], incident["focal_node"], incident["title"],
                incident["severity"], incident.get("status", "open"), incident["detected_at"],
                incident["window_start"], incident["window_end"],
                top.get("root_cause", ""), top.get("confidence", 0.0), json.dumps(incident)
            )
        await self.audit(incident["incident_id"], "system", "incident_created",
                         f"{incident['title']} ({incident['severity']})")

    async def list_incidents(self, limit: int = 100) -> list[dict]:
        if self.pool is None:
            return []
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT incident_id, focal_node, title, severity, status, detected_at, "
                "top_cause, top_confidence FROM incidents ORDER BY detected_at DESC LIMIT $1",
                limit
            )
        return [dict(r) for r in rows]

    async def get_incident(self, incident_id: str) -> dict | None:
        if self.pool is None:
            return None
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT data FROM incidents WHERE incident_id=$1", incident_id)
        return json.loads(row["data"]) if row else None

    async def set_status(self, incident_id: str, status: str, actor: str = "operator") -> None:
        inc = await self.get_incident(incident_id)
        if inc:
            inc["status"] = status
            async with self.pool.acquire() as conn:
                await conn.execute("UPDATE incidents SET status=$1, data=$2 WHERE incident_id=$3",
                                   status, json.dumps(inc), incident_id)
        await self.audit(incident_id, actor, "status_change", status)

    # ---------- feedback learning loop ----------
    async def save_feedback(self, entry: dict) -> None:
        """Upsert an operator's Correct/Wrong judgement on a hypothesis.

        UNIQUE(incident_id, hypothesis_rank, actor) means a re-vote (a "flip")
        overwrites the prior row rather than appending — so the net-vote math in
        feedback_boost_map() never double-counts.
        """
        if self.pool is None:
            raise RuntimeError("PostgreSQL store is not initialized")
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO rca_feedback
                   (feedback_id, incident_id, focal_node, hypothesis_rank,
                    hypothesis_kind, root_cause, is_correct, actor, ts)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                   ON CONFLICT (incident_id, hypothesis_rank, actor) DO UPDATE SET
                   is_correct=EXCLUDED.is_correct,
                   hypothesis_kind=EXCLUDED.hypothesis_kind,
                   root_cause=EXCLUDED.root_cause,
                   focal_node=EXCLUDED.focal_node,
                   ts=EXCLUDED.ts""",
                entry["feedback_id"], entry["incident_id"], entry.get("focal_node"),
                entry["hypothesis_rank"], entry["hypothesis_kind"], entry.get("root_cause", ""),
                entry["is_correct"], entry["actor"], entry["ts"],
            )

    async def list_feedback(self, incident_id: str) -> list[dict]:
        if self.pool is None:
            return []
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT feedback_id, incident_id, focal_node, hypothesis_rank, "
                "hypothesis_kind, root_cause, is_correct, actor, ts "
                "FROM rca_feedback WHERE incident_id=$1 ORDER BY hypothesis_rank",
                incident_id,
            )
        return [dict(r) for r in rows]

    async def feedback_boost_map(self) -> dict:
        """Net-vote boost map across all feedback, grouped by node+kind and by kind.
        See aggregate_feedback_rows for the (flip-safe) reduction."""
        if self.pool is None:
            return {"node_kind": {}, "kind": {}}
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT focal_node, hypothesis_kind, is_correct FROM rca_feedback"
            )
        return aggregate_feedback_rows([dict(r) for r in rows])

    async def update_incident_field(self, incident_id: str, key: str, value: Any) -> None:
        inc = await self.get_incident(incident_id)
        if not inc:
            return
        inc[key] = value
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE incidents SET data=$1 WHERE incident_id=$2",
                               json.dumps(inc), incident_id)

    async def audit(self, incident_id: str, actor: str, action: str, detail: str = "") -> None:
        if self.pool is None:
            return
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO audit_log (ts, incident_id, actor, action, detail) VALUES ($1,$2,$3,$4,$5)",
                time.time(), incident_id, actor, action, detail
            )

    async def audit_trail(self, incident_id: str | None = None, limit: int = 200) -> list[dict]:
        if self.pool is None:
            return []
        async with self.pool.acquire() as conn:
            if incident_id:
                rows = await conn.fetch(
                    "SELECT id, ts, incident_id, actor, action, detail FROM audit_log WHERE incident_id=$1 ORDER BY ts DESC LIMIT $2",
                    incident_id, limit
                )
            else:
                rows = await conn.fetch(
                    "SELECT id, ts, incident_id, actor, action, detail FROM audit_log ORDER BY ts DESC LIMIT $1", limit
                )
        return [dict(r) for r in rows]

    async def stats(self) -> dict:
        if self.pool is None:
            return {"total_incidents": 0, "open_incidents": 0}
        async with self.pool.acquire() as conn:
            n = await conn.fetchval("SELECT COUNT(*) FROM incidents")
            open_ = await conn.fetchval("SELECT COUNT(*) FROM incidents WHERE status='open'")
        return {"total_incidents": n, "open_incidents": open_}


store = Store()
