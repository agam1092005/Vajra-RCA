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
