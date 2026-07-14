"""Qdrant client and RAG system.

Indexes runbooks, troubleshooting manuals, and SOPs.
Uses Google Gemini text embeddings (text-embedding-004).
When Gemini is unavailable, uses a STABLE TF-IDF-style hash that produces
consistent vectors across process restarts (PYTHONHASHSEED is bypassed by
using hashlib, not Python's built-in hash()).
"""
from __future__ import annotations

import hashlib
import math

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

from ..core.config import settings

COLLECTION_NAME = "vajra_sop"
VECTOR_SIZE = 768  # text-embedding-004 dimension


def _stable_hash_embedding(text: str) -> list[float]:
    """Produce a stable, reproducible 768-dim vector from text.

    Unlike numpy.random.RandomState(hash(text)) this is consistent across
    process restarts because we use hashlib (not Python's randomised hash()).

    Algorithm: SHA-256 of each 4-char n-gram → normalised float components
    across VECTOR_SIZE dimensions using multiple hash seeds.
    """
    vec = [0.0] * VECTOR_SIZE
    words = text.lower().split()
    # Build character n-gram tokens
    tokens = []
    for w in words:
        tokens.append(w)
        for n in (3, 4):
            tokens.extend(w[i: i + n] for i in range(max(0, len(w) - n + 1)))

    for token in tokens:
        digest = hashlib.sha256(token.encode()).digest()
        # Map each pair of bytes to a dimension index and a value
        for i in range(0, min(len(digest), VECTOR_SIZE * 2), 2):
            dim = int.from_bytes(digest[i: i + 2], "little") % VECTOR_SIZE
            val = (digest[i] / 255.0) * 2 - 1          # map [0,255] → [-1, 1]
            vec[dim] += val

    # L2-normalise
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


# ── SOP catalogue ───────────────────────────────────────────────────────────

_SOPS = [
    {
        "title": "Redis Connection Timeouts & Recovery",
        "text": (
            "SOP-101: Redis is unavailable or connection is timing out. "
            "Steps: (1) Verify Redis status: 'docker compose ps'. "
            "(2) Check if port 6379 is listening. "
            "(3) Trigger container restart: 'docker compose restart redis'. "
            "(4) Validate API gateway latency after reboot."
        ),
        "source": "redis_runbook.md",
    },
    {
        "title": "Network Latency & Routing Misconfiguration",
        "text": (
            "SOP-102: Latency spike or packet loss detected after router routing table updates. "
            "Steps: (1) Check recent routing rule commits in git config repo. "
            "(2) Roll back routing.yaml changes. "
            "(3) Verify gateway routes using 'traceroute'. "
            "(4) Inspect config_change events in the audit trail."
        ),
        "source": "network_ops.md",
    },
    {
        "title": "Mitigating Distributed Denial of Service (DDoS)",
        "text": (
            "SOP-103: Extreme volume of external flows, classified as DoS or Exploits. "
            "Steps: (1) Rate-limit target source IPs. "
            "(2) Enable inline security filter. "
            "(3) Validate packet loss rates and check processes on the affected hosts. "
            "(4) Review UNSW anomaly labels for attack categories."
        ),
        "source": "security_sop.md",
    },
    {
        "title": "Database Connection Pool Exhaustion",
        "text": (
            "SOP-104: PostgreSQL database returning 500 server errors or connection pool full. "
            "Steps: (1) Inspect connection count: 'SELECT count(*) FROM pg_stat_activity'. "
            "(2) Increase connection limits or restart Postgres service. "
            "(3) Check dependent microservices for retry storms."
        ),
        "source": "db_runbook.md",
    },
    {
        "title": "Anomaly Spike: Isolation Forest & Kitsune Alert",
        "text": (
            "SOP-105: Multiple ML detectors (Isolation Forest, Kitsune) flagged anomalous traffic. "
            "Steps: (1) Check anomaly_score and reconstruction_error in incident attributes. "
            "(2) Identify source IP and destination port pattern. "
            "(3) Correlate with recent config changes. "
            "(4) Review blast radius in the topology graph."
        ),
        "source": "anomaly_runbook.md",
    },
    {
        "title": "Backdoor & Shellcode Detection Response",
        "text": (
            "SOP-106: UNSW attack_cat=Backdoor or Shellcode detected. "
            "Steps: (1) Immediately isolate the affected host. "
            "(2) Capture network traffic for forensics. "
            "(3) Review upstream dependencies in Neo4j topology. "
            "(4) Rotate credentials and apply patches."
        ),
        "source": "security_sop.md",
    },
    {
        "title": "Config Change Rollback Procedure",
        "text": (
            "SOP-107: A recent git commit to routing.yaml or service config caused anomalies. "
            "Steps: (1) Identify the commit hash from config_change event actor field. "
            "(2) Run: git revert <commit>. "
            "(3) Verify UNSW flows normalise within 60 seconds. "
            "(4) Update the Vajra RCA audit trail with rollback action."
        ),
        "source": "config_runbook.md",
    },
    {
        "title": "HDFS Log Error Escalation",
        "text": (
            "SOP-108: HDFS block errors or DataNode failures detected in log stream. "
            "Steps: (1) Check HDFS block_id in the incident attributes. "
            "(2) Run: hdfs fsck / to identify corrupt blocks. "
            "(3) Restart affected DataNode containers. "
            "(4) Monitor replication recovery."
        ),
        "source": "hdfs_runbook.md",
    },
]


class RAGClient:
    def __init__(self) -> None:
        self.client: QdrantClient | None = None
        self._initialized = False

    def initialize(self) -> None:
        """Connect to Qdrant, (re)create collection and seed all SOPs."""
        try:
            self.client = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
            # Always recreate the collection so embeddings are fresh and consistent
            collections = self.client.get_collections().collections
            exists = any(c.name == COLLECTION_NAME for c in collections)

            if exists:
                # Check point count — if 0 or mismatched, reseed
                count = self.client.count(COLLECTION_NAME).count
                if count < len(_SOPS):
                    print(f"[Qdrant] Collection exists but only {count}/{len(_SOPS)} SOPs. Reseeding.")
                    self.client.delete_collection(COLLECTION_NAME)
                    exists = False

            if not exists:
                self.client.create_collection(
                    collection_name=COLLECTION_NAME,
                    vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
                )
                self._seed_sops()
            else:
                print(f"[Qdrant] Collection '{COLLECTION_NAME}' ready with {self.client.count(COLLECTION_NAME).count} SOPs.")

            self._initialized = True
        except Exception as e:
            print(f"[Qdrant] Initialization warning: {e}. RAG features will degrade gracefully.")
            self.client = None

    def _get_embedding(self, text: str) -> list[float]:
        """Return an embedding vector.

        Priority:
          1. Google text-embedding-004 (requires VAJRA_GOOGLE_API_KEY)
          2. Stable hash embedding (consistent across restarts, no API needed)
        """
        if settings.google_api_key and settings.google_api_key != "YOUR_GOOGLE_API_KEY_HERE":
            try:
                from google import genai
                client = genai.Client(api_key=settings.google_api_key)
                resp = client.models.embed_content(
                    model="text-embedding-004",
                    contents=text,
                )
                return resp.embeddings[0].values
            except Exception as e:
                print(f"[Qdrant] Embeddings API error: {e}. Using stable hash fallback.")

        # Stable deterministic fallback — consistent across process restarts
        return _stable_hash_embedding(text)

    def _seed_sops(self) -> None:
        """Upsert all SOPs into Qdrant."""
        if not self.client:
            return
        print(f"[Qdrant] Seeding {len(_SOPS)} SOPs …")
        points = []
        for i, s in enumerate(_SOPS):
            emb = self._get_embedding(s["title"] + " " + s["text"])
            points.append(PointStruct(id=i, vector=emb, payload=s))
        self.client.upsert(collection_name=COLLECTION_NAME, points=points)
        print(f"[Qdrant] Seeded {len(points)} SOPs.")

    def search_sops(self, query: str, limit: int = 3) -> list[dict]:
        """Query vector database for similar SOPs.

        Returns a list of payload dicts (title, text, source).
        Falls back to keyword matching if Qdrant is unavailable.
        """
        if not self.client:
            return self._keyword_fallback(query, limit)
        try:
            vector = self._get_embedding(query)
            results = self.client.query_points(
                collection_name=COLLECTION_NAME,
                query=vector,
                limit=limit,
            )
            docs = [r.payload for r in results.points if r.payload]
            if not docs:
                # No vector matches — fall back to keyword
                return self._keyword_fallback(query, limit)
            return docs
        except Exception as e:
            print(f"[Qdrant] Search failed: {e}. Using keyword fallback.")
            return self._keyword_fallback(query, limit)

    def _keyword_fallback(self, query: str, limit: int) -> list[dict]:
        """Simple keyword overlap fallback when Qdrant is unreachable.

        Scores each SOP by how many query words appear in its text.
        Always returns at least something — never an empty list for a real query.
        """
        q_words = set(query.lower().split())
        scored = []
        for sop in _SOPS:
            combined = (sop["title"] + " " + sop["text"]).lower()
            score = sum(1 for w in q_words if w in combined)
            scored.append((score, sop))
        scored.sort(key=lambda x: x[0], reverse=True)
        # Return top matches, always at least 1 even with score=0
        return [s for _, s in scored[:limit]]


# Module-level singleton
rag = RAGClient()
