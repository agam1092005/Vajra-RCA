"""Individual nodes for the 8-agent LangGraph diagnostic pipeline.

Coordinator -> Metric -> Log -> Trace -> Graph -> RAG -> RootCause -> Report.
"""
from __future__ import annotations

import time
from typing import Any

from .state import AgentState
from ..core.events import Event, EventType, Severity
from ..core import tracing
from ..graph.topology import TopologyGraph
from ..rag.graphrag import graphrag          # GraphRAG = Qdrant + Neo4j
from ..db.store import store
from ..llm import gemini
from ..rca.engine import RCAEngine
from ..rca.scoring import apply_feedback_boosts


# Module-level topology singleton — one Neo4j connection shared across all agent calls.
_topo: TopologyGraph | None = None
_topo_ready = False


def _get_topo() -> TopologyGraph | None:
    """Return the topology singleton, initialising once on first call."""
    global _topo, _topo_ready
    if _topo_ready:
        return _topo
    _topo_ready = True
    t = TopologyGraph()
    try:
        t.initialize()
        _topo = t
    except Exception as exc:
        print(f"[Agents] Neo4j unavailable: {exc}")
        _topo = None
    return _topo


MAX_RAW_EVENTS = 300   # bound state size regardless of how wide the caller's window was
MAX_LOG_ENTRIES = 40
MAX_TRACE_SPANS = 40


def coordinator_node(state: AgentState) -> dict[str, Any]:
    with tracing.span("agent.coordinator", focal_node=state["focal_node"], agent="coordinator"):
        print(f"[Coordinator] Initiating root-cause diagnostic graph for node: {state['focal_node']}")
        # Distill to the most recent N events up front so every downstream node —
        # and anything later serialized into the LLM prompt — operates on a bounded,
        # already-relevant slice instead of an unbounded raw event list.
        events = sorted(state["raw_events"], key=lambda e: e.timestamp)[-MAX_RAW_EVENTS:]
        return {"raw_events": events}


def metric_node(state: AgentState) -> dict[str, Any]:
    with tracing.span("agent.metric", focal_node=state["focal_node"], agent="metric"):
        print(f"[Metric Agent] Scanning telemetry metrics for {state['focal_node']}")
        events = state["raw_events"]
        node = state["focal_node"]

        anom_events = [e for e in events if e.node == node and e.event_type == EventType.ANOMALY]
        avg_score = sum(e.attributes.get("anomaly_score", 0.0) for e in anom_events) / max(1, len(anom_events))

        return {
            "metrics": {
                "flow_count": len([e for e in events if e.node == node and e.event_type == EventType.NETWORK_FLOW]),
                "anomaly_count": len(anom_events),
                "average_anomaly_score": round(avg_score, 4),
                "max_severity": max((e.severity.value for e in anom_events), default="info")
            }
        }


def log_node(state: AgentState) -> dict[str, Any]:
    with tracing.span("agent.log", focal_node=state["focal_node"], agent="log"):
        print(f"[Log Agent] Examining logs for {state['focal_node']}")
        # Query HDFS log events inside window
        logs = []
        for e in state["raw_events"]:
            if e.event_type == EventType.LOG or e.source == "hdfs":
                if e.attributes.get("is_error") or e.severity in (Severity.HIGH, Severity.CRITICAL):
                    logs.append({
                        "timestamp": e.timestamp,
                        "level": e.attributes.get("level", "ERROR"),
                        "component": e.node,
                        "text": e.description
                    })
        return {"logs": logs[-MAX_LOG_ENTRIES:]}


def trace_node(state: AgentState) -> dict[str, Any]:
    """Real OTel spans, not simulated: reads the in-process ring buffer that
    every ingestion/detection/topology/RCA/agent operation exports spans into
    (see core/tracing.py). Filtered to spans touching this incident's focal
    node within its event window, so what the Trace Agent reports is genuine
    captured span data — the same spans the graph/root-cause agents just
    produced while diagnosing this incident."""
    focal_node = state["focal_node"]
    with tracing.span("agent.trace", focal_node=focal_node, agent="trace") as current:
        print(f"[Trace Agent] Reading real OTel spans for {focal_node}")
        window_start = min((e.timestamp for e in state["raw_events"]), default=None)
        spans = tracing.recent_spans(focal_node=focal_node, since=window_start, limit=MAX_TRACE_SPANS)
        current.set_attribute("spans_found", len(spans))
        return {"traces": spans}


def graph_node(state: AgentState) -> dict[str, Any]:
    with tracing.span("agent.graph", focal_node=state["focal_node"], agent="graph") as current:
        print(f"[Graph Agent] Walking dependency topology in Neo4j for {state['focal_node']}")
        topo = _get_topo()
        if topo is None:
            return {"dependencies": {"upstream": [], "downstream": [], "blast_radius_nodes": [], "blast_radius_count": 0, "levels": []}}
        try:
            upstream = topo.upstream_dependencies(state["focal_node"])
            downstream = topo.downstream_dependents(state["focal_node"])
            blast = topo.blast_radius(state["focal_node"])
            current.set_attribute("blast_radius_count", blast.get("count", 0))
            return {
                "dependencies": {
                    "upstream": upstream,
                    "downstream": downstream,
                    "blast_radius_nodes": blast.get("impacted", []),
                    "blast_radius_count": blast.get("count", 0),
                    "levels": blast.get("levels", [])
                }
            }
        except Exception as e:
            print(f"[Graph Agent] Neo4j dependency lookup failed: {e}")
            return {"dependencies": {"upstream": [], "downstream": [], "blast_radius_nodes": [], "blast_radius_count": 0, "levels": []}}


def rag_node(state: AgentState) -> dict[str, Any]:
    with tracing.span("agent.rag", focal_node=state["focal_node"], agent="rag"):
        print(f"[RAG Agent] GraphRAG: Qdrant + Neo4j search for {state['focal_node']}")
        try:
            # Build query from focal node + any anomaly/alert event descriptions
            anom_descs = [
                e.signature for e in state["raw_events"]
                if e.event_type.value in ("anomaly", "security_alert") and e.signature
            ][:3]
            query = f"network anomaly on {state['focal_node']}"
            if anom_descs:
                query = f"{' '.join(anom_descs)} on {state['focal_node']}"
            docs = graphrag.search(query, focal_node=state["focal_node"], limit=3)
            return {"rag_documents": docs}
        except Exception as e:
            print(f"[RAG Agent] GraphRAG lookup failed: {e}")
            return {"rag_documents": []}


def root_cause_node(state: AgentState) -> dict[str, Any]:
    with tracing.span("agent.root_cause", focal_node=state["focal_node"], agent="root_cause") as current:
        print(f"[Root Cause Agent] Running causal inference scoring...")
        topo = _get_topo()
        if topo is None:
            # Fallback: build a minimal topology just for the RCA engine
            topo_fallback = TopologyGraph()
            engine = RCAEngine(topo_fallback)
        else:
            engine = RCAEngine(topo)
        try:
            # Build incident deterministically using the RCAEngine logic
            incident = engine.build_incident(
                focal_node=state["focal_node"],
                window_events=state["raw_events"],
                history=state["history"],
                downstream_nodes=state.get("downstream_nodes", []),
            )

            # Award historical_pattern_match bonus when GraphRAG found a matching runbook
            hypotheses = incident.hypotheses
            if state["rag_documents"] and hypotheses:
                for h in hypotheses:
                    matching = [
                        doc for doc in state["rag_documents"]
                        if doc.get("source") and h.get("kind", "") in doc.get("text", "").lower()
                    ]
                    if matching:
                        h["score_breakdown"]["historical_pattern_match"] = 10
                        h["confidence"] = min(1.0, h["confidence"] + 0.1)

            # Feedback learning loop: apply the operator's confirmed/rejected past
            # judgements (capped ±15) then re-sort + re-rank so a boosted hypothesis
            # visibly rises to #1. Node-scoped feedback wins, global per-kind is the
            # fallback (see rca.scoring.apply_feedback_boosts).
            hypotheses = apply_feedback_boosts(
                hypotheses, state["focal_node"], state.get("feedback_boosts") or {})

            current.set_attribute("hypothesis_count", len(hypotheses))
            return {"hypotheses": hypotheses}
        except Exception as e:
            print(f"[Root Cause Agent] Causal inference failed: {e}")
            return {"hypotheses": []}


def report_node(state: AgentState) -> dict[str, Any]:
    with tracing.span("agent.report", focal_node=state["focal_node"], agent="report"):
        print(f"[Report Agent] Synthesizing natural-language incident report...")
        import uuid
        # Calculate real severity based on the maximum severity of raw alerts and anomalies
        primary_events = [e for e in state["raw_events"] if e.event_type in (EventType.ANOMALY, EventType.SECURITY_ALERT)]
        _SEV_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
        sev_val = max(primary_events, key=lambda e: _SEV_ORDER.get(e.severity.value, 0)).severity.value if primary_events else "low"

        temp_incident = {
            "incident_id": "lg_" + uuid.uuid4().hex[:10],
            "focal_node": state["focal_node"],
            "title": f"Causal Anomaly on {state['focal_node']}",
            "severity": sev_val,
            "window_start": min((e.timestamp for e in state["raw_events"]), default=time.time()),
            "window_end": max((e.timestamp for e in state["raw_events"]), default=time.time()),
            "detected_at": time.time(),
            "summary": f"Incident under review on {state['focal_node']}.",
            "hypotheses": state["hypotheses"],
            "timeline": [],
            "signal_counts": {
                "anomalies": len([e for e in state["raw_events"] if e.event_type == EventType.ANOMALY]),
                "alerts": len([e for e in state["raw_events"] if e.event_type == EventType.SECURITY_ALERT]),
                "config_changes": len([e for e in state["raw_events"] if e.event_type == EventType.CONFIG_CHANGE])
            }
        }

        # Generate timeline
        for e in state["raw_events"]:
            if e.event_type != EventType.NETWORK_FLOW or e.node == state["focal_node"]:
                temp_incident["timeline"].append({
                    "timestamp": e.timestamp,
                    "time": time.strftime("%H:%M:%S", time.gmtime(e.timestamp)),
                    "type": e.event_type.value, "node": e.node, "severity": e.severity.value,
                    "text": e.signature or e.description, "source": e.source,
                })
        temp_incident["timeline"] = sorted(temp_incident["timeline"], key=lambda x: x["timestamp"])[:20]

        topo = _get_topo()
        engine = RCAEngine(topo) if topo is not None else RCAEngine(TopologyGraph())
        br_dict = {
            "impacted": state["dependencies"].get("blast_radius_nodes", []),
            "count": state["dependencies"].get("blast_radius_count", 0),
            "depth": len(state["dependencies"].get("levels", [])),
            "levels": state["dependencies"].get("levels", [])
        }
        business_impact = engine._calculate_business_impact(state["focal_node"], state["hypotheses"], br_dict, state["raw_events"])
        temp_incident["business_impact"] = business_impact

        # Use the fast deterministic explanation here so the pipeline never blocks
        # incident creation/emission on a live LLM round-trip. The richer Gemini
        # narrative is generated on demand via POST /api/incidents/{id}/explain.
        explanation = gemini.deterministic_explanation(temp_incident)

        final_report = {
            **temp_incident,
            "title": temp_incident["hypotheses"][0]["root_cause"] if temp_incident["hypotheses"] else temp_incident["title"],
            "severity": temp_incident["hypotheses"][0].get("severity", temp_incident["severity"]) if temp_incident["hypotheses"] else temp_incident["severity"],
            "summary": temp_incident["hypotheses"][0].get("explanation", temp_incident["summary"]) if temp_incident["hypotheses"] else temp_incident["summary"],
            "explanation": explanation,
            "blast_radius": br_dict,
            "rag_docs": state["rag_documents"],
            # Real OTel spans captured for this incident's diagnostic run (see agent.trace).
            "trace_spans": state["traces"],
        }

        return {"final_report": final_report}
