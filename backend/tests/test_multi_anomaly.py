"""Fix A (all concurrent candidates per tick) + Fix D (deterministic same-ms ordering).

Both are verified without Neo4j/Qdrant/Gemini: Fix D exercises the real RCAEngine
sort/timeline paths directly; Fix A drives Pipeline._maybe_incident with _run_agents
and the store stubbed so only the loop logic is under test.
"""
import asyncio

import pytest

from app.core.events import Event, EventType, Severity
from app.graph.topology import TopologyGraph
from app.rca.engine import RCAEngine
from app.pipeline import Pipeline


def _sig(node, ts, ingested):
    e = Event(event_type=EventType.ANOMALY, source="isolation_forest", node=node,
              timestamp=ts, severity=Severity.HIGH, signature="s",
              attributes={"signature": {}, "attribution": []})
    object.__setattr__(e, "ingested_at", ingested)
    return e


# ---------- Fix D: deterministic sub-millisecond ordering ----------

def test_same_timestamp_events_order_by_ingested_at():
    """Config change and anomaly share an identical timestamp; the config was ingested
    first, so after the engine's stable sort it must precede the anomaly — the causal
    'cause precedes effect' precondition stays reproducible."""
    eng = RCAEngine(TopologyGraph())
    ts = 100.0
    cfg = Event(event_type=EventType.CONFIG_CHANGE, source="config_monitor", node="n1",
                timestamp=ts, severity=Severity.MEDIUM, description="cfg")
    object.__setattr__(cfg, "ingested_at", 1.0)
    anom = _sig("n1", ts, ingested=2.0)

    # Feed in the WRONG order; the (timestamp, ingested_at) sort must fix it.
    inc = eng.build_incident("n1", [anom, cfg])
    types = [t["type"] for t in inc.timeline]
    assert types.index("config_change") < types.index("anomaly")


def test_timeline_stable_under_shuffle():
    eng = RCAEngine(TopologyGraph())
    evs = [_sig("n1", 100.0, ingested=float(i)) for i in range(5)]
    import random
    shuffled = evs[:]
    random.shuffle(shuffled)
    tl = eng.build_incident("n1", shuffled).timeline
    ingested_order = [t["ingested_at"] for t in tl if t["type"] == "anomaly"]
    assert ingested_order == sorted(ingested_order)


# ---------- Fix A: every concurrent candidate node surfaces ----------

def test_maybe_incident_raises_all_concurrent_nodes(monkeypatch):
    """Three distinct nodes each cross the signal threshold in the same window; the
    tick must raise an incident for each (up to the cap), not just the strongest."""
    pipe = Pipeline()
    pipe.rca = RCAEngine(pipe.topology)

    # 6 anomalies on each of 3 nodes, all in-window.
    now = 1000.0
    for node in ("nodeA", "nodeB", "nodeC"):
        for i in range(6):
            pipe.window.append(_sig(node, now, ingested=float(i)))

    raised_nodes = []

    async def fake_run_agents(node, related, downstream_nodes=None):
        raised_nodes.append(node)
        return {"incident_id": node, "title": f"inc-{node}", "severity": "high", "hypotheses": []}

    async def fake_save(_):
        return None

    monkeypatch.setattr(pipe, "_run_agents", fake_run_agents)
    monkeypatch.setattr("app.pipeline.store.save_incident", fake_save)
    monkeypatch.setattr(pipe, "emit", lambda *a, **k: None)

    asyncio.run(pipe._maybe_incident())

    # cap defaults to 3 -> all three concurrent nodes get an incident.
    assert set(raised_nodes) == {"nodeA", "nodeB", "nodeC"}
    assert pipe.open_incidents_count == 3


def test_per_tick_cap_bounds_incident_storm(monkeypatch):
    pipe = Pipeline()
    pipe.rca = RCAEngine(pipe.topology)
    pipe.max_incidents_per_tick = 2

    now = 1000.0
    for node in ("a", "b", "c", "d"):
        for i in range(6):
            pipe.window.append(_sig(node, now, ingested=float(i)))

    raised = []
    async def fake_run_agents(node, related, downstream_nodes=None):
        raised.append(node)
        return {"incident_id": node, "title": node, "severity": "high", "hypotheses": []}
    monkeypatch.setattr(pipe, "_run_agents", fake_run_agents)
    monkeypatch.setattr("app.pipeline.store.save_incident", lambda _: asyncio.sleep(0))
    monkeypatch.setattr(pipe, "emit", lambda *a, **k: None)

    asyncio.run(pipe._maybe_incident())
    assert len(raised) == 2  # capped
