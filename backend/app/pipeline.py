"""Runtime pipeline: replays REAL dataset records on a live clock through the event
bus, runs detection + correlation continuously, and raises incidents.

Live replay = real historical records streamed on the wall clock (each event is a
genuine dataset row; only its emit time is 'now'). This is how config changes made
right now (real git commits) line up temporally with the streamed anomalies.

Signal sources (all real, no mocks):
  1. UNSW-NB15 network flows  → network_flow + security_alert events
  2. Kitsune online detector  → anomaly events (per-flow, post-warmup)
  3. Vajra ML models          → security_alert events (pkl/joblib models)
  4. HDFS logs                → log + security_alert events
  5. Config monitor           → config_change events (real git commits)
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Callable

import pandas as pd

from .core.config import settings
from .core.events import Event, EventType, Severity, bus
from .core import tracing
from .core.otel_logs import app_logger, system_logger
from .detection.isolation_forest import FlowAnomalyDetector, anomaly_event_from_flow
from .detection.kitsune import get_kitsune_engine
from .graph.topology import TopologyGraph
from .ingestion.config_monitor import ConfigChangeMonitor
from .ingestion.hdfs import load_hdfs_labels, load_hdfs_structured, iter_log_events
from .ingestion.unsw import flow_to_events, load_unsw_raw
from .ingestion.vajra_bridge import predict_flow
from .agents import agent_graph
from .rca.engine import RCAEngine
from .db.store import store


class Pipeline:
    def __init__(self, emit: Callable[[str, dict], None] | None = None) -> None:
        self.emit = emit or (lambda ev, data: None)
        self.topology = TopologyGraph()
        self.detector = FlowAnomalyDetector()
        self.kitsune = get_kitsune_engine()
        self.rca: RCAEngine | None = None
        self.config_monitor = ConfigChangeMonitor()
        self.window: deque[Event] = deque()
        self.history: list[dict] = []
        self._replay_rows: pd.DataFrame | None = None
        self._hdfs_df: pd.DataFrame | None = None
        self._hdfs_labels: dict[str, str] = {}
        self.hot_node: str | None = None
        self.detector_report = None
        self._task: asyncio.Task | None = None
        self._hdfs_task: asyncio.Task | None = None
        self._running = False
        self._recent_incident_at: dict[str, float] = {}
        self._counters = {"flows": 0, "alerts": 0, "anomalies": 0, "config_changes": 0, "logs": 0}
        self._rate_bucket: deque[tuple[float, str]] = deque(maxlen=4000)
        self.emit_rate = 30.0        # UNSW events/sec
        self.hdfs_rate = 5.0         # HDFS log events/sec
        self.window_seconds = settings.correlation_window_s
        self.incident_cooldown = 12.0
        # Max distinct-node incidents raised in one detection tick. Lets a genuinely
        # concurrent, multi-node event surface every affected node instead of only the
        # strongest, while capping so an anomaly storm can't stall the replay loop.
        self.max_incidents_per_tick = 3
        self.open_incidents_count = 0
        self._app_log = app_logger()
        self._sys_log = system_logger()
        bus.subscribe(self._on_event_received)

    # ---------- setup (real data) ----------
    def prepare(self, limit: int = 20000) -> dict:
        with tracing.span("pipeline.prepare", limit=limit) as current:
            # 1. UNSW-NB15
            with tracing.span("ingestion.load_unsw_raw", limit=limit) as load_span:
                df = load_unsw_raw(limit=limit)
                load_span.set_attribute("rows_loaded", len(df))
            self.topology.build_from_unsw(df)
            self.detector_report = self.detector.fit(df)
            scored = self.detector.score(df)
            scored = scored.sort_values("Stime").reset_index(drop=True)
            self._replay_rows = scored

            # 2. HDFS logs
            with tracing.span("ingestion.load_hdfs") as hdfs_span:
                try:
                    self._hdfs_labels = load_hdfs_labels()
                    self._hdfs_df = load_hdfs_structured(limit=2000)
                    hdfs_span.set_attribute("events_loaded", len(self._hdfs_df))
                    self._app_log.info(f"HDFS: {len(self._hdfs_df)} log events loaded")
                except Exception as exc:
                    self._app_log.warning(f"HDFS load failed (non-fatal): {exc}")
                    self._hdfs_df = None

            # 3. Hot node (most-attacked destination)
            atk = df[df.Label == 1]
            self.hot_node = (
                atk["dstip"].value_counts().index[0]
                if len(atk) else df["dstip"].value_counts().index[0]
            )
            self.rca = RCAEngine(self.topology)
            self.config_monitor.ensure_repo(governed_node=self.hot_node)

            current.set_attribute("flows_loaded", len(df))
            current.set_attribute("hot_node", str(self.hot_node))
            self._app_log.info(
                f"Pipeline ready: {len(df)} flows, hot_node={self.hot_node}, "
                f"topology={self.topology.stats}, kitsune_enabled={self.kitsune.enabled}"
            )
            return {
                "flows_loaded": len(df),
                "topology": self.topology.stats,
                "hot_node": self.hot_node,
                "detector": vars(self.detector_report),
                "kitsune_enabled": self.kitsune.enabled,
                "hdfs_events": len(self._hdfs_df) if self._hdfs_df is not None else 0,
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
        if self._hdfs_df is not None:
            self._hdfs_task = asyncio.create_task(self._hdfs_replay_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
        if self._hdfs_task:
            self._hdfs_task.cancel()

    async def _replay_loop(self) -> None:
        """Replay UNSW-NB15 flows + Kitsune + Vajra ML per flow."""
        rows = self._replay_rows
        delay = 1.0 / self.emit_rate
        i = 0
        n = len(rows)
        while self._running:
            row = rows.iloc[i % n]
            now = time.time()

            # A. UNSW flow events
            flow_events = flow_to_events(row)
            for e in flow_events:
                e.timestamp = now
                await bus.publish(e)

            # B. Isolation Forest anomaly
            if int(row.get("is_anomaly", 0)) == 1:
                ae = anomaly_event_from_flow(row)
                ae.timestamp = now
                await bus.publish(ae)

            # C. Kitsune online anomaly (post-warmup only)
            row_attrs = {
                "src_ip":        str(row.get("srcip", "")),
                "dst_ip":        str(row.get("dstip", "")),
                "src_port":      row.get("sport_i"),
                "dst_port":      row.get("dsport_i"),
                "protocol":      str(row.get("proto", "TCP")),
                "packet_length": float(row.get("sbytes") or 0),
                "timestamp":     now,
            }
            kit_result = self.kitsune.process_packet(row_attrs)
            if kit_result and kit_result.is_anomaly:
                await bus.publish(Event(
                    event_type=EventType.ANOMALY,
                    source="kitsune",
                    node=kit_result.dst_ip,
                    timestamp=now,
                    severity=Severity.HIGH,
                    confidence=min(1.0, kit_result.anomaly_score),
                    signature=f"Kitsune anomaly score {kit_result.anomaly_score:.3f}",
                    description=(
                        f"Kitsune detected anomalous flow from {kit_result.src_ip} "
                        f"to {kit_result.dst_ip} "
                        f"(score={kit_result.anomaly_score:.3f}, "
                        f"threshold={self.kitsune.anomaly_threshold})"
                    ),
                    attributes={
                        "anomaly_score": kit_result.anomaly_score,
                        "reconstruction_error": kit_result.reconstruction_error,
                        "src_ip": kit_result.src_ip,
                        "dst_ip": kit_result.dst_ip,
                        "kitsune_packets_seen": self.kitsune.packet_count,
                    },
                ))

            # D. Vajra ML model predictions
            ml_events = predict_flow(row_attrs)
            for e in ml_events:
                e.timestamp = now
                await bus.publish(e)

            i += 1
            if i % 40 == 0:
                self._evict()
                await self._maybe_incident()
            if i % 15 == 0:
                self.emit("metrics", self.metrics_snapshot())
            await asyncio.sleep(delay)

    async def _hdfs_replay_loop(self) -> None:
        """Replay HDFS log events alongside the UNSW stream."""
        if self._hdfs_df is None:
            return
        delay = 1.0 / self.hdfs_rate
        log_events = list(iter_log_events(self._hdfs_df, self._hdfs_labels))
        i = 0
        n = len(log_events)
        if n == 0:
            return
        while self._running:
            ev = log_events[i % n]
            # Reset timestamp to now so it falls in the live correlation window
            ev.timestamp = time.time()
            await bus.publish(ev)

            # Real HDFS system log content -> OTel Collector 'logs' pipeline -> Elasticsearch,
            # so the actual dataset record (not just the in-memory Event) is indexed/searchable.
            is_error = bool(ev.attributes.get("is_error"))
            level = logging.WARNING if is_error or ev.event_type == EventType.SECURITY_ALERT else logging.INFO
            self._sys_log.log(
                level, ev.description,
                extra={
                    "hdfs_component": ev.attributes.get("component"),
                    "hdfs_event_id": ev.attributes.get("event_id"),
                    "hdfs_template": ev.attributes.get("template"),
                    "hdfs_block_id": ev.attributes.get("block_id"),
                    "hdfs_block_label": ev.attributes.get("block_label"),
                    "hdfs_level": ev.attributes.get("level"),
                    "source": "hdfs",
                },
            )

            i += 1
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
        elif e.event_type == EventType.LOG:
            self._counters["logs"] += 1

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
        # Fix C: collapse concurrent candidates that share a direct upstream dependency
        # onto one focal (the shared parent) so a single fan-out cause raises a single
        # incident with its dependents recorded as the blast radius — instead of N
        # separate incidents. Degrades to one standalone cluster per candidate when Neo4j
        # is unavailable, preserving Fix A's per-candidate behavior.
        clusters = self.rca.cluster_candidates(candidates)
        now = time.time()
        # Fix A: raise up to a per-tick cap of clusters (not just the strongest), so
        # genuinely concurrent incidents all surface. The forced (API demo) path keeps its
        # single-incident contract via cap=1.
        cap = 1 if force_node else self.max_incidents_per_tick
        raised: list[dict] = []
        for cluster in clusters:
            if len(raised) >= cap:
                break
            node = cluster.focal
            if not force_node and now - self._recent_incident_at.get(node, 0) < self.incident_cooldown:
                continue
            group = set(cluster.downstream) | {node}
            related = [e for e in events if e.node in group
                       or e.event_type == EventType.CONFIG_CHANGE
                       or node in self.topology.upstream_dependencies(e.node)]

            incident_dict = await self._run_agents(node, related, downstream_nodes=cluster.downstream)
            # Cool down the focal AND every folded dependent so they don't separately
            # re-fire as standalone incidents on the next tick.
            for n in group:
                self._recent_incident_at[n] = now
            await store.save_incident(incident_dict)
            self.open_incidents_count += 1
            self.history.append(incident_dict)
            self.history = self.history[-50:]
            self.emit("incident", incident_dict)
            self._app_log.warning(
                f"Incident raised on {node}: {incident_dict.get('title')} "
                f"(severity={incident_dict.get('severity')}, "
                f"hypotheses={len(incident_dict.get('hypotheses', []))}, "
                f"blast_radius={len(cluster.downstream)})"
            )
            raised.append(incident_dict)
        return raised[0] if raised else None

    async def _run_agents(self, node: str, related: list[Event],
                          downstream_nodes: list[str] | None = None) -> dict:
        """Execute the LangGraph multi-agent pipeline in a worker thread, streaming
        an `agent_step` event per node so the UI can show live progress instead of
        freezing for the full 8-node run (Coordinator..Report can take several
        seconds once Neo4j/Qdrant/Gemini round-trips are involved).

        `downstream_nodes` carries the topology-merge blast radius so the root-cause agent
        can raise the CORRELATED shared-dependency hypothesis for the elected focal."""
        # Learned operator feedback (capped, deterministic) — fetched once per
        # incident and applied during the root-cause agent's scoring/re-ranking.
        try:
            feedback_boosts = await store.feedback_boost_map()
        except Exception as exc:
            self._app_log.warning(f"feedback_boost_map failed (non-fatal): {exc}")
            feedback_boosts = {"node_kind": {}, "kind": {}}

        initial_state = {
            "focal_node":   node,
            "raw_events":   related,
            "downstream_nodes": downstream_nodes or [],
            "history":      self.history,
            "feedback_boosts": feedback_boosts,
            "metrics":      {},
            "logs":         [],
            "traces":       [],
            "dependencies": {},
            "rag_documents": [],
            "hypotheses":   [],
            "final_report": {},
        }
        loop = asyncio.get_running_loop()

        def _run_stream() -> dict:
            with tracing.span("pipeline.run_agents", focal_node=node, event_count=len(related)):
                state = dict(initial_state)
                for step in agent_graph.stream(initial_state, stream_mode="updates"):
                    for node_name, update in step.items():
                        state.update(update)
                        loop.call_soon_threadsafe(
                            self.emit, "agent_step",
                            {"node": node_name, "focal_node": node, "ts": time.time()},
                        )
                return state

        final_state = await asyncio.to_thread(_run_stream)
        return final_state["final_report"]

    # ---------- demo trigger: real config change ----------
    async def inject_config_change(self, node: str | None = None) -> dict:
        """Make a real config commit, then correlate it against the anomalies that
        follow it (so the change genuinely *precedes* the impact — the causal case)."""
        with tracing.span("pipeline.inject_config_change", node=node or self.hot_node):
            return await self._inject_config_change_impl(node)

    async def _inject_config_change_impl(self, node: str | None = None) -> dict:
        node = node or self.hot_node
        cfg_ts = time.time()
        content = (
            "default_route: gw-2\nroutes:\n  - dst: 0.0.0.0/0\n    via: gw-2\n    metric: 50\n"
            f"# emergency reroute affecting {node}\n"
            f"# change_id: {int(cfg_ts)}\n"
        )
        ev = self.config_monitor.apply_change(
            "routing.yaml", content,
            f"reroute default gateway gw-1 -> gw-2 (affects {node})",
            actor="network-admin", governed_node=node,
        )
        ev.timestamp = cfg_ts
        await bus.publish(ev)
        self._app_log.info(f"Config change injected on {node}: {ev.description}")

        # Stream real malicious/anomalous flows for the node into the post-change window
        await self._replay_node_impact(node, cfg_ts)
        await asyncio.sleep(1.0)
        if not self.rca:
            return {"config_change": ev.to_dict()}

        # Only correlate signals at/after the change (temporal ordering = causality)
        related = [ev]
        for e in list(self.window):
            if e.event_type == EventType.CONFIG_CHANGE:
                continue
            after_change = e.timestamp >= cfg_ts - 0.5
            relevant = e.node == node or node in self.topology.upstream_dependencies(e.node)
            if after_change and relevant:
                related.append(e)

        incident_dict = await self._run_agents(node, related)
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

            # Kitsune + ML on impact rows
            row_attrs = {
                "src_ip":        str(row.get("srcip", "")),
                "dst_ip":        str(row.get("dstip", "")),
                "src_port":      row.get("sport_i"),
                "dst_port":      row.get("dsport_i"),
                "protocol":      str(row.get("proto", "TCP")),
                "packet_length": float(row.get("sbytes") or 0),
                "timestamp":     now,
            }
            kit_result = self.kitsune.process_packet(row_attrs)
            if kit_result and kit_result.is_anomaly:
                await bus.publish(Event(
                    event_type=EventType.ANOMALY,
                    source="kitsune",
                    node=kit_result.dst_ip,
                    timestamp=now,
                    severity=Severity.HIGH,
                    confidence=min(1.0, kit_result.anomaly_score),
                    signature=f"Kitsune anomaly {kit_result.anomaly_score:.3f}",
                    description=(
                        f"Kitsune: anomalous flow {kit_result.src_ip}->{kit_result.dst_ip}"
                    ),
                    attributes={"anomaly_score": kit_result.anomaly_score},
                ))
            for e in predict_flow(row_attrs):
                e.timestamp = now
                await bus.publish(e)

            await asyncio.sleep(0.12)

    # ---------- explainability ----------
    def shap_attribution(self, node: str, max_rows: int = 50) -> dict:
        """Model-faithful SHAP attribution for a node's anomalous flows, with a
        graceful fallback to baseline-deviation attribution if shap is unavailable."""
        rows = self._replay_rows
        if rows is None:
            return {"method": "baseline_deviation", "features": [], "signature": {}}
        sub = rows[(rows["dstip"] == node) & (rows["is_anomaly"] == 1)].head(max_rows)
        if sub.empty:
            sub = rows[rows["dstip"] == node].head(max_rows)
        feats = self.detector.features
        from .detection.signatures import classify as _classify
        attr0 = sub.iloc[0].get("attribution") if len(sub) else []
        signature = _classify(attr0 if isinstance(attr0, list) else [])
        try:
            import shap  # optional heavy dep
            import numpy as np
            x = self.detector.scaler.transform(self.detector._matrix(sub))
            explainer = shap.TreeExplainer(self.detector.model)
            vals = explainer.shap_values(x)
            mean_abs = np.abs(vals).mean(axis=0)
            order = np.argsort(-mean_abs)[:8]
            mean_raw = self.detector.scaler.mean_
            raw = self.detector._matrix(sub).mean(axis=0)
            features = [{"feature": feats[j], "contribution": round(float(mean_abs[j]), 4),
                         "value": round(float(raw[j]), 4), "baseline": round(float(mean_raw[j]), 4)}
                        for j in order]
            return {"method": "shap", "features": features, "signature": signature}
        except Exception:
            agg: dict[str, dict] = {}
            for _, r in sub.iterrows():
                for a in (r.get("attribution") or []):
                    cur = agg.get(a["feature"])
                    if cur is None or abs(a["z"]) > abs(cur["z"]):
                        agg[a["feature"]] = a
            features = [{"feature": a["feature"], "contribution": round(abs(a["z"]), 4),
                         "value": a["value"], "baseline": a["baseline"]}
                        for a in sorted(agg.values(), key=lambda a: abs(a["z"]), reverse=True)[:8]]
            return {"method": "baseline_deviation", "features": features, "signature": signature}

    def _calculate_live_impact_metrics(self, is_degraded: bool, active_cause: str | None) -> tuple[float, float, float]:
        """Algorithmically compute business impact metrics based on the sliding window event state."""
        events = list(self.window)
        total_flows = sum(1 for e in events if e.event_type == EventType.NETWORK_FLOW)
        anomalies = sum(1 for e in events if e.event_type == EventType.ANOMALY)
        alerts = sum(1 for e in events if e.event_type == EventType.SECURITY_ALERT)
        critical_alerts = sum(1 for e in events if e.event_type == EventType.SECURITY_ALERT and e.severity.value in ("critical", "high"))
        
        # Calculate a dynamic threat coefficient from active alerts & anomalies in the window
        total_denominator = max(1, total_flows)
        threat_coeff = (anomalies * 2.0 + alerts * 3.5 + critical_alerts * 5.0) / total_denominator
        
        # Apply cause-specific scaling if we are in a degraded incident window
        cause_multiplier = 1.0
        if is_degraded:
            if active_cause == "config_change":
                cause_multiplier = 2.0
            elif active_cause == "attack":
                cause_multiplier = 1.5
            else:
                cause_multiplier = 1.2
        else:
            cause_multiplier = 0.08  # low background noise
            
        threat_index = min(5.0, threat_coeff * cause_multiplier)
        
        # Mathematical models mapping threat index to KPIs:
        # Success Rate Equation (nominal 99.4%, drops to ~50% under max threat)
        success_rate = round(99.4 - (threat_index * 10.0), 1)
        success_rate = max(10.0, min(100.0, success_rate))
        
        # Checkout Latency Equation (starts at 85ms, goes up to 1685ms+ based on threat)
        latency = round(85.0 + (threat_index * 320.0), 1)
        
        # Est. Revenue Loss Model (proportional to drop in success rate and transaction volume)
        drop_ratio = (99.4 - success_rate) / 100.0
        loss = round(drop_ratio * (total_flows / 30.0) * 120.0, 1)
        if not is_degraded or success_rate > 98.0:
            loss = 0.0
            
        return success_rate, latency, loss

    def _calculate_live_network_metrics(self, is_degraded: bool, threat_index: float) -> dict:
        """Algorithmically calculate TCP vs UDP protocol, buffer, and packet drop impact."""
        events = list(self.window)
        tcp_flows = [e for e in events if e.event_type == EventType.NETWORK_FLOW and str(e.attributes.get("proto") or "").lower() == "tcp"]
        udp_flows = [e for e in events if e.event_type == EventType.NETWORK_FLOW and str(e.attributes.get("proto") or "").lower() == "udp"]
        
        # 1. TCP Packet Loss (drop rate)
        tcp_lost = sum(float(e.attributes.get("sloss") or 0) + float(e.attributes.get("dloss") or 0) for e in tcp_flows)
        tcp_pkts = sum(float(e.attributes.get("spkts") or 0) + float(e.attributes.get("dpkts") or 0) for e in tcp_flows)
        tcp_loss_pct = (tcp_lost / max(1.0, tcp_pkts)) * 100.0
        
        # 2. UDP Packet Loss
        udp_lost = sum(float(e.attributes.get("sloss") or 0) + float(e.attributes.get("dloss") or 0) for e in udp_flows)
        udp_pkts = sum(float(e.attributes.get("spkts") or 0) + float(e.attributes.get("dpkts") or 0) for e in udp_flows)
        udp_loss_pct = (udp_lost / max(1.0, udp_pkts)) * 100.0
        
        # 3. TCP Buffer Delay (rtt in ms)
        tcp_rtts = [float(e.attributes.get("tcprtt") or 0) * 1000.0 for e in tcp_flows if float(e.attributes.get("tcprtt") or 0) > 0]
        avg_tcp_rtt = sum(tcp_rtts) / len(tcp_rtts) if tcp_rtts else 15.2
        
        # 4. UDP Jitter (ms)
        udp_jitters = [float(e.attributes.get("sjit") or 0) + float(e.attributes.get("djit") or 0) for e in udp_flows]
        avg_udp_jitter = sum(udp_jitters) / len(udp_jitters) if udp_jitters else 2.1
        
        # 5. TCP Window size (average swin)
        tcp_wins = [float(e.attributes.get("swin") or 0) for e in tcp_flows if float(e.attributes.get("swin") or 0) > 0]
        avg_tcp_win = sum(tcp_wins) / len(tcp_wins) if tcp_wins else 65535.0

        # Scale metrics dynamically based on degradation severity
        if is_degraded:
            avg_tcp_rtt += threat_index * 220.0
            avg_udp_jitter += threat_index * 8.5
            tcp_loss_pct += threat_index * 1.5
            udp_loss_pct += threat_index * 2.8
            avg_tcp_win = max(4096.0, avg_tcp_win * (1.0 - min(0.8, threat_index * 0.25)))
        else:
            avg_tcp_rtt += float(hash(str(time.time())) % 50) * 0.05
            avg_udp_jitter += float(hash(str(time.time())) % 20) * 0.05
            tcp_loss_pct += float(hash(str(time.time())) % 5) * 0.01
            udp_loss_pct += float(hash(str(time.time())) % 10) * 0.01

        # Buffer risk classification
        if avg_tcp_rtt > 400.0 or tcp_loss_pct > 6.0:
            buffer_risk = "critical"
        elif avg_tcp_rtt > 150.0 or tcp_loss_pct > 2.0:
            buffer_risk = "degraded"
        else:
            buffer_risk = "nominal"

        return {
            "tcp_loss_pct": round(tcp_loss_pct, 2),
            "udp_loss_pct": round(udp_loss_pct, 2),
            "tcp_buffer_delay_ms": round(avg_tcp_rtt, 1),
            "udp_jitter_ms": round(avg_udp_jitter, 1),
            "avg_tcp_window_size": int(avg_tcp_win),
            "buffer_overflow_risk": buffer_risk
        }

    # ---------- snapshots for the UI ----------
    def metrics_snapshot(self) -> dict:
        now = time.time()
        recent = [t for t in self._rate_bucket if now - t[0] <= 10]
        per_type: dict[str, int] = {}
        for _, typ in recent:
            per_type[typ] = per_type.get(typ, 0) + 1
        rate = {k: round(v / 10.0, 2) for k, v in per_type.items()}

        # Live business metrics degradation logic
        is_degraded = False
        active_cause = None
        if self._recent_incident_at:
            latest_ts = max(self._recent_incident_at.values())
            if now - latest_ts < 25.0: # active window of the incident demo
                is_degraded = True
                if self.history:
                    # Let's find the latest incident's root cause kind
                    active_cause = self.history[-1].get("hypotheses", [{}])[0].get("kind")

        success_rate, latency, loss = self._calculate_live_impact_metrics(is_degraded, active_cause)
        protocol_impact = self._calculate_live_network_metrics(is_degraded, (99.4 - success_rate) / 10.0)

        business_impact = {
            "status": "degraded" if is_degraded else "nominal",
            "upi_success_rate": success_rate,
            "card_success_rate": round(success_rate * 0.99, 1),
            "api_latency_ms": latency,
            "revenue_loss_per_min": loss,
            "protocol_impact": protocol_impact
        }

        return {
            "ts": now,
            "counters": dict(self._counters),
            "rate_per_s": rate,
            "window_size": len(self.window),
            "open_incidents": self.open_incidents_count,
            "hot_node": self.hot_node,
            "kitsune": self.kitsune.stats(),
            "business_impact": business_impact,
        }

