"""Individual nodes for the 8-agent LangGraph diagnostic pipeline.

Coordinator -> Metric -> Log -> Trace -> Graph -> RAG -> RootCause -> Report.
"""
from __future__ import annotations

import time
from typing import Any

from .state import AgentState
from ..core.events import Event, EventType, Severity
from ..graph.topology import TopologyGraph
from ..rag.qdrant import rag
from ..db.store import store
from ..llm import gemini
from ..rca.engine import RCAEngine


# Shared topology graph client for the agents
_topo = TopologyGraph()


def coordinator_node(state: AgentState) -> dict[str, Any]:
    print(f"[Coordinator] Initiating root-cause diagnostic graph for node: {state['focal_node']}")
    return {}


def metric_node(state: AgentState) -> dict[str, Any]:
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
    return {"logs": logs}


def trace_node(state: AgentState) -> dict[str, Any]:
    print(f"[Trace Agent] Parsing transaction trace spans for {state['focal_node']}")
    # Simulating OpenTelemetry spans / latencies extracted from telemetry events
    traces = []
    for e in state["raw_events"]:
        if e.event_type == EventType.NETWORK_FLOW and e.node == state["focal_node"]:
            sbytes = float(e.attributes.get("sbytes") or 0)
            dbytes = float(e.attributes.get("dbytes") or 0)
            # High bytes transfers in UNSW serve as trace propagation signals
            if sbytes + dbytes > 1000000:
                traces.append({
                    "span_id": e.event_id[:8],
                    "src": e.attributes.get("srcip"),
                    "dst": e.node,
                    "bytes_transferred": sbytes + dbytes,
                    "latency_ms": round(sbytes / 50000.0, 2)
                })
    return {"traces": traces}


def graph_node(state: AgentState) -> dict[str, Any]:
    print(f"[Graph Agent] Walking dependency topology in Neo4j for {state['focal_node']}")
    try:
        _topo.initialize()
        upstream = _topo.upstream_dependencies(state["focal_node"])
        downstream = _topo.downstream_dependents(state["focal_node"])
        blast = _topo.blast_radius(state["focal_node"])
        
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
        return {"dependencies": {"upstream": [], "downstream": [], "blast_radius_nodes": [], "blast_radius_count": 0}}


def rag_node(state: AgentState) -> dict[str, Any]:
    print(f"[RAG Agent] Searching similar incident runbooks in Qdrant for {state['focal_node']}")
    try:
        # Search for SOPs based on focal node and anomaly details
        query = f"network anomaly or latency on {state['focal_node']}"
        sops = rag.search_sops(query, limit=2)
        return {"rag_documents": sops}
    except Exception as e:
        print(f"[RAG Agent] Qdrant SOP lookup failed: {e}")
        return {"rag_documents": []}


def root_cause_node(state: AgentState) -> dict[str, Any]:
    print(f"[Root Cause Agent] Running causal inference scoring...")
    try:
        _topo.initialize()
        engine = RCAEngine(_topo)
        
        # Build incident deterministically using the RCAEngine logic
        incident = engine.build_incident(
            focal_node=state["focal_node"],
            window_events=state["raw_events"],
            history=state["history"]
        )
        
        # Add Qdrant RAG matches as a historical evidence factor in the hypotheses
        hypotheses = incident.hypotheses
        if state["rag_documents"] and hypotheses:
            for h in hypotheses:
                # Add points to confidence score if a runbook matches the root cause kind
                if any(doc.get("source") for doc in state["rag_documents"]):
                    h["score_breakdown"]["historical_pattern_match"] = 10
                    h["confidence"] = min(1.0, h["confidence"] + 0.1)
                    
        return {"hypotheses": hypotheses}
    except Exception as e:
        print(f"[Root Cause Agent] Causal inference failed: {e}")
        return {"hypotheses": []}


def report_node(state: AgentState) -> dict[str, Any]:
    print(f"[Report Agent] Synthesizing natural-language incident report...")
    import uuid
    # Mock/deterministic default incident structure to feed explain_incident
    temp_incident = {
        "incident_id": "lg_" + uuid.uuid4().hex[:10],
        "focal_node": state["focal_node"],
        "title": f"Causal Anomaly on {state['focal_node']}",
        "severity": "high",
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

    # Generate natural language explanation using Gemini
    explanation = gemini.explain_incident(temp_incident)
    
    final_report = {
        **temp_incident,
        "title": temp_incident["hypotheses"][0]["root_cause"] if temp_incident["hypotheses"] else temp_incident["title"],
        "severity": temp_incident["hypotheses"][0].get("severity", "high") if temp_incident["hypotheses"] else "high",
        "summary": temp_incident["hypotheses"][0].get("explanation", temp_incident["summary"]) if temp_incident["hypotheses"] else temp_incident["summary"],
        "explanation": explanation,
        "blast_radius": {
            "impacted": state["dependencies"].get("blast_radius_nodes", []),
            "count": state["dependencies"].get("blast_radius_count", 0),
            "depth": len(state["dependencies"].get("levels", [])),
            "levels": state["dependencies"].get("levels", [])
        },
        "rag_docs": state["rag_documents"]
    }
    
    return {"final_report": final_report}
