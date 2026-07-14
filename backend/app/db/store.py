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
