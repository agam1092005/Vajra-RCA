"""Qdrant client and RAG system.

Indexes runbooks, troubleshooting manuals, and SOPs.
Uses Google Gemini text embeddings (with a deterministic vector fallback when offline).
"""
from __future__ import annotations

import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

from ..core.config import settings

COLLECTION_NAME = "vajra_sop"
VECTOR_SIZE = 768  # text-embedding-004 dimension


class RAGClient:
    def __init__(self) -> None:
        self.client: QdrantClient | None = None

    def initialize(self) -> None:
        """Connect to Qdrant and seed initial runbooks/SOPs."""
        try:
            self.client = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
            # Check if collection exists, if not create it
            collections = self.client.get_collections().collections
            exists = any(c.name == COLLECTION_NAME for c in collections)
            if not exists:
                self.client.create_collection(
                    collection_name=COLLECTION_NAME,
                    vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE)
                )
                self.seed_sops()
        except Exception as e:
            print(f"[Qdrant] Initialization warning: {e}. RAG features will degrade gracefully.")
            self.client = None

    def _get_embedding(self, text: str) -> list[float]:
        """Fetch Google text embeddings or fallback deterministically if offline."""
        if settings.google_api_key:
            try:
                from google import genai
                client = genai.Client(api_key=settings.google_api_key)
                resp = client.models.embed_content(
                    model="text-embedding-004",
                    contents=text
                )
                return resp.embeddings[0].values
            except Exception as e:
                print(f"[Qdrant] Embeddings API error: {e}. Using deterministic fallback.")
        
        # Deterministic offline fallback (sentence hashing to 768 float array)
        state = np.random.RandomState(abs(hash(text)) % (2**32))
        return state.randn(VECTOR_SIZE).tolist()

    def seed_sops(self) -> None:
        """Seed the vector store with standard operations procedures (SOPs)."""
        if not self.client:
            return
        sops = [
            {
                "title": "Redis Connection Timeouts & Recovery",
                "text": "SOP-101: Redis is unavailable or connection is timing out. Steps: (1) Verify Redis status: 'docker compose ps'. (2) Check if port 6379 is listening. (3) Trigger container restart: 'docker compose restart redis'. (4) Validate API gateway latency after reboot.",
                "source": "redis_runbook.md"
            },
            {
                "title": "Network Latency & Routing Misconfiguration",
                "text": "SOP-102: Latency spike or packet loss detected after router routing table updates. Steps: (1) Check recent routing rule commits in git config repo. (2) Roll back routing.yaml changes. (3) Verify gateway routes using 'traceroute'.",
                "source": "network_ops.md"
            },
            {
                "title": "Mitigating Distributed Denial of Service (DDoS)",
                "text": "SOP-103: Extreme volume of external flows, classified as DoS or Exploits. Steps: (1) Rate-limit target source IPs. (2) Enable inline security filter. (3) Validate packet loss rates and check processes on the affected hosts.",
                "source": "security_sop.md"
            },
            {
                "title": "Database Connection Pool Exhaustion",
                "text": "SOP-104: PostgreSQL database returning 500 server errors or connection pool full. Steps: (1) Inspect connection count: 'SELECT count(*) FROM pg_stat_activity'. (2) Increase connection limits or restart Postgres service.",
                "source": "db_runbook.md"
            }
        ]

        points = []
        for i, s in enumerate(sops):
            emb = self._get_embedding(s["text"])
            points.append(PointStruct(
                id=i,
                vector=emb,
                payload=s
            ))
        
        self.client.upsert(collection_name=COLLECTION_NAME, points=points)

    def search_sops(self, query: str, limit: int = 2) -> list[dict]:
        """Query vector database for similar SOPs."""
        if not self.client:
            return []
        try:
            vector = self._get_embedding(query)
            results = self.client.query_points(
                collection_name=COLLECTION_NAME,
                query=vector,
                limit=limit
            )
            return [r.payload for r in results.points]
        except Exception as e:
            print(f"[Qdrant] Search failed: {e}")
            return []


rag = RAGClient()
