"""LangGraph agent state schema.

Maintains the shared context between all 8 diagnostic agents.
"""
from __future__ import annotations

from typing import Any, TypedDict
from ..core.events import Event


class AgentState(TypedDict):
    # Context
    focal_node: str
    raw_events: list[Event]
    # Downstream dependents folded onto this focal by the topology merge (blast radius).
    # Empty for a standalone incident; drives the CORRELATED shared-dependency hypothesis.
    downstream_nodes: list[str]
    history: list[dict[str, Any]]
    feedback_boosts: dict[str, Any]
    
    # Agent collections
    metrics: dict[str, Any]
    logs: list[dict[str, Any]]
    traces: list[dict[str, Any]]
    dependencies: dict[str, Any]
    rag_documents: list[dict[str, Any]]
    
    # Hypotheses & Outputs
    hypotheses: list[dict[str, Any]]
    final_report: dict[str, Any]
