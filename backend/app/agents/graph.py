"""LangGraph Multi-Agent Diagnostic Workflow.

Orchestrates the Coordinator, Metric, Log, Trace, Graph, RAG, Root Cause and Report agents.
"""
from __future__ import annotations

from langgraph.graph import StateGraph, START, END

from .state import AgentState
from .nodes import (
    coordinator_node,
    metric_node,
    log_node,
    trace_node,
    graph_node,
    rag_node,
    root_cause_node,
    report_node
)


def create_agent_graph():
    """Build and compile the multi-agent diagnostic graph."""
    workflow = StateGraph(AgentState)
    
    # 1. Register all nodes
    workflow.add_node("coordinator", coordinator_node)
    workflow.add_node("metric", metric_node)
    workflow.add_node("log", log_node)
    workflow.add_node("trace", trace_node)
    workflow.add_node("graph", graph_node)
    workflow.add_node("rag", rag_node)
    workflow.add_node("root_cause", root_cause_node)
    workflow.add_node("report", report_node)
    
    # 2. Add straight-through execution path
    workflow.add_edge(START, "coordinator")
    workflow.add_edge("coordinator", "metric")
    workflow.add_edge("metric", "log")
    workflow.add_edge("log", "trace")
    workflow.add_edge("trace", "graph")
    workflow.add_edge("graph", "rag")
    workflow.add_edge("rag", "root_cause")
    workflow.add_edge("root_cause", "report")
    workflow.add_edge("report", END)
    
    return workflow.compile()


# Compile the global graph instance
agent_graph = create_agent_graph()
