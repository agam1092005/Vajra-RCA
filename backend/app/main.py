"""FastAPI + Socket.IO application entrypoint.

Serves the REST API and live event stream for the dashboard, and drives the
real-time replay pipeline over the real datasets.
"""
from __future__ import annotations

import asyncio

import socketio
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .core.config import settings
from .core.serialize import to_jsonable
from .core.events import bus
from .db.store import store
from .llm import gemini
from .pipeline import Pipeline
from .rag.qdrant import rag
from .utils.reporter import generate_and_upload_report

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
api = FastAPI(title="Vajra RCA — Network Anomaly Root-Cause Assistant", version="0.1.0")
api.add_middleware(
    CORSMiddleware, allow_origins=settings.cors_origins + ["*"],
    allow_methods=["*"], allow_headers=["*"], allow_credentials=True,
)


def _emit(event: str, data: dict) -> None:
    """Sync bridge from the pipeline into Socket.IO (schedules an async emit)."""
    try:
        asyncio.get_running_loop().create_task(sio.emit(event, to_jsonable(data)))
    except RuntimeError:
        pass


pipeline = Pipeline(emit=_emit)
_status: dict = {"ready": False}


@api.on_event("startup")
async def _startup() -> None:
    # 1. Connect to Postgres
    await store.initialize()
    # 2. Connect to Qdrant
    rag.initialize()
    # 3. Connect to Kafka
    await bus.start()
    
    # 4. Prepare pipeline and fit detector (runs in threadpool)
    summary = await asyncio.to_thread(pipeline.prepare)
    _status.update(to_jsonable(summary))
    _status["ready"] = True
    
    # 5. Live telemetry replay defaults to stopped (real-time only listening mode)
    # await pipeline.start()


@api.on_event("shutdown")
async def _shutdown() -> None:
    await pipeline.stop()
    await bus.stop()
    pipeline.topology.close()


# ------------------------- REST -------------------------
@api.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "ready": _status.get("ready", False)}


@api.get("/api/status")
async def status() -> dict:
    return to_jsonable({**_status, "db": await store.stats()})


@api.get("/api/metrics")
async def metrics() -> dict:
    return to_jsonable(pipeline.metrics_snapshot())


@api.get("/api/topology")
async def topology(top_n: int = 60) -> dict:
    return to_jsonable(pipeline.topology.to_cytoscape(top_n=top_n))


@api.get("/api/topology/node/{node}")
async def topology_node(node: str) -> dict:
    return to_jsonable({
        **pipeline.topology.node_view(node),
        "blast_radius": pipeline.topology.blast_radius(node),
    })


@api.get("/api/incidents")
async def incidents(limit: int = 100) -> list[dict]:
    return to_jsonable(await store.list_incidents(limit=limit))


@api.get("/api/incidents/{incident_id}")
async def incident(incident_id: str) -> dict:
    inc = await store.get_incident(incident_id)
    if not inc:
        raise HTTPException(404, "incident not found")
    return to_jsonable(inc)


@api.get("/api/incidents/{incident_id}/audit")
async def incident_audit(incident_id: str) -> list[dict]:
    return to_jsonable(await store.audit_trail(incident_id))


@api.post("/api/incidents/{incident_id}/explain")
async def explain(incident_id: str) -> dict:
    inc = await store.get_incident(incident_id)
    if not inc:
        raise HTTPException(404, "incident not found")
    explanation = await asyncio.to_thread(gemini.explain_incident, inc)
    await store.update_incident_field(incident_id, "explanation", explanation)
    await store.audit(incident_id, "assistant", "explanation_generated", explanation.get("generated_by", ""))
    return to_jsonable(explanation)


@api.post("/api/incidents/{incident_id}/report")
async def get_report(incident_id: str) -> dict:
    inc = await store.get_incident(incident_id)
    if not inc:
        raise HTTPException(404, "incident not found")
    report_url = await asyncio.to_thread(generate_and_upload_report, inc)
    await store.update_incident_field(incident_id, "report_url", report_url)
    await store.audit(incident_id, "operator", "report_generated", report_url)
    return {"report_url": report_url}


class ReplayToggleIn(BaseModel):
    active: bool


@api.get("/api/telemetry/replay/status")
async def get_replay_status() -> dict:
    return {"active": pipeline.replay_active}


@api.post("/api/telemetry/replay/toggle")
async def toggle_replay(body: ReplayToggleIn) -> dict:
    if body.active:
        await pipeline.start()
    else:
        await pipeline.stop()
    return {"active": pipeline.replay_active}


class ChatIn(BaseModel):
    question: str


@api.post("/api/incidents/{incident_id}/chat")
async def chat(incident_id: str, body: ChatIn) -> dict:
    inc = await store.get_incident(incident_id)
    if not inc:
        raise HTTPException(404, "incident not found")
    ans = await asyncio.to_thread(gemini.chat, inc, body.question)
    await store.audit(incident_id, "operator", "chat", body.question[:120])
    return to_jsonable(ans)


class StatusIn(BaseModel):
    status: str
    actor: str = "operator"


@api.post("/api/incidents/{incident_id}/status")
async def set_status(incident_id: str, body: StatusIn) -> dict:
    if not await store.get_incident(incident_id):
        raise HTTPException(404, "incident not found")
    await store.set_status(incident_id, body.status, body.actor)
    return {"ok": True, "status": body.status}


class InjectIn(BaseModel):
    node: str | None = None


@api.post("/api/inject/config-change")
async def inject_config(body: InjectIn) -> dict:
    result = await pipeline.inject_config_change(body.node)
    return to_jsonable(result)


@api.get("/api/audit")
async def audit(limit: int = 200) -> list[dict]:
    return to_jsonable(await store.audit_trail(limit=limit))


# ------------------------- Socket.IO -------------------------
@sio.event
async def connect(sid, environ):
    await sio.emit("metrics", to_jsonable(pipeline.metrics_snapshot()), to=sid)


# ASGI app that serves both FastAPI (REST) and Socket.IO
app = socketio.ASGIApp(sio, other_asgi_app=api)
