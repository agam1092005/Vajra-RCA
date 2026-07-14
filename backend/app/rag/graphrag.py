"""GraphRAG — Combined Qdrant vector search + Neo4j topology traversal.

For a given query + focal_node:
1. Qdrant vector search finds semantically similar SOPs / past incidents.
2. Neo4j topology traversal enriches each match with related nodes
   (upstream dependencies, downstream dependents) of the focal node.

This turns raw runbook matches into topology-aware answers:
"SOP-102 (routing misconfiguration) is relevant AND the affected node
 has 3 upstream dependencies that are also in the blast radius."
"""
from __future__ import annotations

from typing import Any

from .qdrant import rag
from ..graph.topology import TopologyGraph


class GraphRAGClient:
    """Topology-aware RAG — Qdrant similarity + Neo4j neighbourhood."""

    def __init__(self) -> None:
        self._topo: TopologyGraph | None = None

    def _topology(self) -> TopologyGraph | None:
        """Lazy-connect to Neo4j; returns None if unreachable."""
        if self._topo is None:
            t = TopologyGraph()
            try:
                t.initialize()
                self._topo = t
            except Exception as exc:
                print(f"[GraphRAG] Neo4j unavailable: {exc}")
                return None
        return self._topo

    def search(
        self,
        query: str,
        focal_node: str | None = None,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        """Return enriched RAG matches.

        Each result:
        {
            "title":          str,
            "text":           str,
            "source":         str,
            "related_nodes":  list[str],   # topology neighbours of focal_node
            "upstream":       list[str],
            "downstream":     list[str],
            "blast_radius":   int,
        }
        """
        # 1. Vector search
        try:
            raw = rag.search_sops(query, limit=limit)
        except Exception as exc:
            print(f"[GraphRAG] Qdrant search failed: {exc}")
            raw = []

        # 2. Topology enrichment
        upstream: list[str] = []
        downstream: list[str] = []
        blast_count = 0

        if focal_node:
            topo = self._topology()
            if topo:
                try:
                    upstream = topo.upstream_dependencies(focal_node)
                    downstream = topo.downstream_dependents(focal_node)
                    blast_info = topo.blast_radius(focal_node)
                    blast_count = blast_info.get("count", 0)
                except Exception:
                    pass

        related = list(set(upstream + downstream))

        results = []
        for doc in raw:
            results.append({
                **doc,
                "related_nodes": related,
                "upstream":       upstream,
                "downstream":     downstream,
                "blast_radius":   blast_count,
            })

        return results

    def search_for_incident(self, incident: dict) -> list[dict[str, Any]]:
        """Convenience wrapper: derive query from top hypothesis + focal node."""
        focal = incident.get("focal_node", "")
        hyps = incident.get("hypotheses", [])
        top = hyps[0] if hyps else {}
        root_cause = top.get("root_cause", "")
        kind = top.get("kind", "")
        query = f"{kind} {root_cause} on {focal}".strip() or f"network anomaly on {focal}"
        return self.search(query, focal_node=focal)


# Module-level singleton
graphrag = GraphRAGClient()
