"""Fix C — topology-aware incident merge (blast-radius deduplication).

Fully stubbed: a FakeTopology supplies the dependency relations, so no Neo4j/Qdrant/Gemini
is required. Covers the clustering algorithm, the elected-focal shared-dependency
hypothesis, and the end-to-end _maybe_incident merge.
"""
import asyncio

from app.core.events import Event, EventType, Severity
from app.rca.engine import RCAEngine, CandidateCluster
from app.rca.scoring import EvidenceKind
from app.pipeline import Pipeline


class FakeTopology:
    """Minimal topology: `deps[node]` = that node's DIRECT upstream dependencies."""
    driver = object()  # non-None so engine paths that guard on it stay active

    def __init__(self, deps: dict[str, list[str]]):
        self.deps = deps

    def upstream_dependencies(self, node):
        return list(self.deps.get(node, []))

    def dependency_path(self, source, target):
        return [source, target] if target in self.deps.get(source, []) else []

    def blast_radius(self, node, max_depth: int = 4):
        impacted = sorted([n for n, ds in self.deps.items() if node in ds])
        return {"impacted": impacted, "count": len(impacted), "depth": 1 if impacted else 0,
                "levels": [impacted] if impacted else []}


def _sig(node, ts=100.0, ingested=1.0):
    e = Event(event_type=EventType.ANOMALY, source="isolation_forest", node=node,
              timestamp=ts, severity=Severity.HIGH, signature="s",
              attributes={"signature": {}, "attribution": []})
    object.__setattr__(e, "ingested_at", ingested)
    return e


def _cands(*nodes):
    return [(n, [_sig(n) for _ in range(6)]) for n in nodes]


# ---------- clustering algorithm ----------

def test_shared_parent_merges_into_one_cluster():
    # orders + api-gateway both depend directly on postgres (which has NO signals).
    topo = FakeTopology({"orders": ["postgres"], "api-gateway": ["postgres"]})
    eng = RCAEngine(topo)
    clusters = eng.cluster_candidates(_cands("orders", "api-gateway"))
    assert len(clusters) == 1
    c = clusters[0]
    assert c.focal == "postgres"
    assert c.downstream == ["api-gateway", "orders"]
    assert c.focal_has_signals is False


def test_no_shared_parent_stays_standalone():
    topo = FakeTopology({"orders": ["postgres"], "search": ["elastic"]})
    eng = RCAEngine(topo)
    clusters = eng.cluster_candidates(_cands("orders", "search"))
    assert {c.focal for c in clusters} == {"orders", "search"}
    assert all(c.downstream == [] for c in clusters)


def test_lca_tiebreak_keeps_lower_parent():
    # a + b both depend directly on pg AND vpc; pg depends on vpc -> keep pg (lower).
    topo = FakeTopology({"a": ["pg", "vpc"], "b": ["pg", "vpc"], "pg": ["vpc"]})
    eng = RCAEngine(topo)
    clusters = eng.cluster_candidates(_cands("a", "b"))
    assert len(clusters) == 1
    assert clusters[0].focal == "pg"


def test_focal_that_is_also_a_candidate_not_duplicated():
    # postgres itself crosses threshold AND is the shared parent of orders + api.
    topo = FakeTopology({"orders": ["postgres"], "api": ["postgres"], "postgres": []})
    eng = RCAEngine(topo)
    clusters = eng.cluster_candidates(_cands("postgres", "orders", "api"))
    assert len(clusters) == 1  # postgres not emitted a second time as standalone
    assert clusters[0].focal == "postgres"
    assert clusters[0].focal_has_signals is True
    assert set(clusters[0].downstream) == {"orders", "api"}


def test_degradation_no_topology_all_standalone():
    topo = FakeTopology({})  # every parent set empty (Neo4j down)
    eng = RCAEngine(topo)
    clusters = eng.cluster_candidates(_cands("n1", "n2", "n3"))
    assert len(clusters) == 3
    assert all(c.downstream == [] for c in clusters)


# ---------- elected-focal hypothesis ----------

def test_shared_dependency_hypothesis_is_correlated_not_confirmed():
    topo = FakeTopology({"orders": ["postgres"], "api": ["postgres"]})
    eng = RCAEngine(topo)
    h = eng._shared_dependency_hypothesis("postgres", ["orders", "api"], history=[])
    assert h is not None
    assert h.kind == "shared_dependency"
    assert h.confirmed_evidence == []                      # never confirmed
    assert "confirmed_match" not in h.score_breakdown
    assert "config_change_within_5s" not in h.score_breakdown
    assert h.correlated_signals                            # fan-out evidence present
    assert h.missing_evidence                              # names the missing direct signal
    assert 0.0 < h.confidence < 1.0
    # dependency paths attached
    assert any("->" in ev["text"] for ev in h.correlated_signals)


# ---------- end-to-end merge in _maybe_incident ----------

def test_maybe_incident_merges_fanout_into_one(monkeypatch):
    topo = FakeTopology({"orders": ["postgres"], "api": ["postgres"], "billing": ["postgres"]})
    pipe = Pipeline()
    pipe.topology = topo
    pipe.rca = RCAEngine(topo)

    for node in ("orders", "api", "billing"):
        for i in range(6):
            pipe.window.append(_sig(node, ingested=float(i)))

    calls = []

    async def fake_run_agents(node, related, downstream_nodes=None):
        calls.append((node, tuple(sorted(downstream_nodes or []))))
        return {"incident_id": node, "title": f"inc-{node}", "severity": "high", "hypotheses": []}

    monkeypatch.setattr(pipe, "_run_agents", fake_run_agents)
    monkeypatch.setattr("app.pipeline.store.save_incident", lambda _: asyncio.sleep(0))
    monkeypatch.setattr(pipe, "emit", lambda *a, **k: None)

    asyncio.run(pipe._maybe_incident())

    # ONE incident, focal postgres, all three dependents as blast radius.
    assert len(calls) == 1
    assert pipe.open_incidents_count == 1
    focal, downstream = calls[0]
    assert focal == "postgres"
    assert downstream == ("api", "billing", "orders")
    # focal + every dependent cooled down (won't re-fire standalone next tick).
    for n in ("postgres", "orders", "api", "billing"):
        assert n in pipe._recent_incident_at
