"""Runtime pipeline: replays REAL dataset records on a live clock through the event
bus, runs detection + correlation continuously, and raises incidents.

Live replay = real historical records streamed on the wall clock (each event is a
genuine dataset row; only its emit time is 'now'). This is how config changes made
right now (real git commits) line up temporally with the streamed anomalies.
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Callable

import pandas as pd

from .core.config import settings
from .core.events import Event, EventType, Severity
from .detection.isolation_forest import FlowAnomalyDetector, anomaly_event_from_flow
from .graph.topology import TopologyGraph
from .ingestion.config_monitor import ConfigChangeMonitor
from .ingestion.unsw import flow_to_events, load_unsw_raw
from .agents import agent_graph
from .rca.engine import RCAEngine
from .core.events import bus, Event
from .db.store import store


class Pipeline:
    def __init__(self, emit: Callable[[str, dict], None] | None = None) -> None:
        self.emit = emit or (lambda ev, data: None)
        self.topology = TopologyGraph()
        self.detector = FlowAnomalyDetector()
        self.rca: RCAEngine | None = None
        self.config_monitor = ConfigChangeMonitor()
        self.window: deque[Event] = deque()
        self.history: list[dict] = []
        self._replay_rows: pd.DataFrame | None = None
        self.hot_node: str | None = None
        self.detector_report = None
        self._task: asyncio.Task | None = None
        self._running = False
        self._recent_incident_at: dict[str, float] = {}
        self._counters = {"flows": 0, "alerts": 0, "anomalies": 0, "config_changes": 0}
        self._rate_bucket: deque[tuple[float, str]] = deque(maxlen=4000)
        self.emit_rate = 30.0            # events/sec streamed
        self.window_seconds = settings.correlation_window_s
        self.incident_cooldown = 12.0
        self.open_incidents_count = 0
        bus.subscribe(self._on_event_received)

    # ---------- setup (real data) ----------
    def prepare(self, limit: int = 20000) -> dict:
        df = load_unsw_raw(limit=limit)
        self.topology.build_from_unsw(df)
        self.detector_report = self.detector.fit(df)
        scored = self.detector.score(df)
        # order the replay stream by the real record start time
        scored = scored.sort_values("Stime").reset_index(drop=True)
        self._replay_rows = scored
        # designate the most-attacked destination as the live "hot" node for the demo
        atk = df[df.Label == 1]
        self.hot_node = atk["dstip"].value_counts().index[0] if len(atk) else df["dstip"].value_counts().index[0]
        self.rca = RCAEngine(self.topology)
        self.config_monitor.ensure_repo(governed_node=self.hot_node)
        return {
            "flows_loaded": len(df), "topology": self.topology.stats,
            "hot_node": self.hot_node, "detector": vars(self.detector_report),
        }

    @property
    def replay_active(self) -> bool:
        return self._running

    # ---------- live replay ----------
    async def start(self) -> None:
        if self._running:
            return
        if self._replay_rows is None:
            self.prepare()
        self._running = True
        self._task = asyncio.create_task(self._replay_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()

    async def _replay_loop(self) -> None:
        rows = self._replay_rows
        delay = 1.0 / self.emit_rate
        i = 0
        n = len(rows)
        while self._running:
            row = rows.iloc[i % n]
            now = time.time()
            for e in flow_to_events(row):
                e.timestamp = now
                await bus.publish(e)
            if int(row.get("is_anomaly", 0)) == 1:
                ae = anomaly_event_from_flow(row)
                ae.timestamp = now
                await bus.publish(ae)
            i += 1
            if i % 40 == 0:
                self._evict()
                await self._maybe_incident()
            if i % 15 == 0:
                self.emit("metrics", self.metrics_snapshot())
            await asyncio.sleep(delay)

    def _on_event_received(self, e: Event) -> None:
        self.window.append(e)
        self._rate_bucket.append((e.timestamp, e.event_type.value))
        if e.event_type == EventType.NETWORK_FLOW:
            self._counters["flows"] += 1
        elif e.event_type == EventType.SECURITY_ALERT:
            self._counters["alerts"] += 1
            self.emit("alert", e.to_dict())
        elif e.event_type == EventType.ANOMALY:
            self._counters["anomalies"] += 1
            self.emit("anomaly", e.to_dict())
        elif e.event_type == EventType.CONFIG_CHANGE:
            self._counters["config_changes"] += 1
            self.emit("config_change", e.to_dict())

    def _evict(self) -> None:
        cutoff = time.time() - self.window_seconds
        while self.window and self.window[0].timestamp < cutoff:
            self.window.popleft()

    async def _maybe_incident(self, force_node: str | None = None) -> dict | None:
        if not self.rca:
            return None
        events = list(self.window)
        candidates = self.rca.find_incident_candidates(events, min_signals=6)
        if force_node:
            candidates = [(force_node, [e for e in events if e.node == force_node
                                        and e.event_type in (EventType.ANOMALY, EventType.SECURITY_ALERT)])] + candidates
        now = time.time()
        for node, _ in candidates:
            if not force_node and now - self._recent_incident_at.get(node, 0) < self.incident_cooldown:
                continue
            related = [e for e in events if e.node == node
                       or e.event_type == EventType.CONFIG_CHANGE
                       or node in self.topology.upstream_dependencies(e.node)]
            
            # Execute LangGraph Multi-Agent pipeline
            initial_state = {
                "focal_node": node,
                "raw_events": related,
                "history": self.history,
                "metrics": {},
                "logs": [],
                "traces": [],
                "dependencies": {},
                "rag_documents": [],
                "hypotheses": [],
                "final_report": {}
            }
            res_state = await asyncio.to_thread(agent_graph.invoke, initial_state)
            incident_dict = res_state["final_report"]
            
            self._recent_incident_at[node] = now
            await store.save_incident(incident_dict)
            self.open_incidents_count += 1
            self.history.append(incident_dict)
            self.history = self.history[-50:]
            self.emit("incident", incident_dict)
            return incident_dict
        return None

    # ---------- demo trigger: real config change ----------
    async def inject_config_change(self, node: str | None = None) -> dict:
        """Make a real config commit, then correlate it against the anomalies that
        follow it (so the change genuinely *precedes* the impact — the causal case)."""
        node = node or self.hot_node
        cfg_ts = time.time()
        content = ("default_route: gw-2\nroutes:\n  - dst: 0.0.0.0/0\n    via: gw-2\n    metric: 50\n"
                   f"# emergency reroute affecting {node}\n"
                   f"# change_id: {int(cfg_ts)}\n")
        ev = self.config_monitor.apply_change(
            "routing.yaml", content,
            f"reroute default gateway gw-1 -> gw-2 (affects {node})",
            actor="network-admin", governed_node=node)
        ev.timestamp = cfg_ts
        await bus.publish(ev)

        # Replay this node's REAL malicious/anomalous records into the post-change
        # window (genuine UNSW rows for `node`, scheduled to stream right after the
        # change) so the causal chain "config change -> impact on node" is observable.
        await self._replay_node_impact(node, cfg_ts)
        await asyncio.sleep(1.0)
        if not self.rca:
            return {"config_change": ev.to_dict()}

        # correlate ONLY signals at/after the change, so temporal ordering holds
        related = [ev]
        for e in list(self.window):
            if e.event_type == EventType.CONFIG_CHANGE:
                continue
            after_change = e.timestamp >= cfg_ts - 0.5
            relevant = e.node == node or node in self.topology.upstream_dependencies(e.node)
            if after_change and relevant:
                related.append(e)
                
        # Execute LangGraph Multi-Agent pipeline
        initial_state = {
            "focal_node": node,
            "raw_events": related,
            "history": self.history,
            "metrics": {},
            "logs": [],
            "traces": [],
            "dependencies": {},
            "rag_documents": [],
            "hypotheses": [],
            "final_report": {}
        }
        res_state = await asyncio.to_thread(agent_graph.invoke, initial_state)
        incident_dict = res_state["final_report"]
        
        self._recent_incident_at[node] = time.time()
        await store.save_incident(incident_dict)
        self.open_incidents_count += 1
        self.history.append(incident_dict)
        self.history = self.history[-50:]
        self.emit("incident", incident_dict)
        return incident_dict

    async def _replay_node_impact(self, node: str, cfg_ts: float, max_rows: int = 18) -> None:
        """Stream real malicious/anomalous flows for `node` into the post-change window."""
        rows = self._replay_rows
        if rows is None:
            return
        impact = rows[(rows["dstip"] == node) & ((rows["is_anomaly"] == 1) | (rows["Label"] == 1))]
        if impact.empty:
            impact = rows[rows["dstip"] == node]
        impact = impact.head(max_rows)
        for _, row in impact.iterrows():
            now = time.time()
            for e in flow_to_events(row):
                e.timestamp = now
                await bus.publish(e)
            if int(row.get("is_anomaly", 0)) == 1:
                ae = anomaly_event_from_flow(row)
                ae.timestamp = now
                await bus.publish(ae)
            await asyncio.sleep(0.12)

    # ---------- snapshots for the UI ----------
    def metrics_snapshot(self) -> dict:
        now = time.time()
        recent = [t for t in self._rate_bucket if now - t[0] <= 10]
        per_type: dict[str, int] = {}
        for _, typ in recent:
            per_type[typ] = per_type.get(typ, 0) + 1
        rate = {k: round(v / 10.0, 2) for k, v in per_type.items()}
        return {
            "ts": now, "counters": dict(self._counters), "rate_per_s": rate,
            "window_size": len(self.window),
            "open_incidents": self.open_incidents_count,
            "hot_node": self.hot_node,
        }
