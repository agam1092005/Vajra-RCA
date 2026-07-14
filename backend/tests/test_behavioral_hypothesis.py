from app.core.events import Event, EventType, Severity
from app.graph.topology import TopologyGraph
from app.rca.engine import RCAEngine


def _anom(node, sig, attr):
    return Event(event_type=EventType.ANOMALY, source="isolation_forest", node=node,
                 timestamp=100.0, severity=Severity.HIGH, signature="x",
                 attributes={"signature": sig, "attribution": attr})


def test_behavioral_hypothesis_explains_scan():
    eng = RCAEngine(TopologyGraph())
    sig = {"label": "port/host scan", "mitre_id": "T1046",
           "mitre_name": "Network Service Discovery",
           "matched_features": ["ct_dst_ltm"], "sentence": "many short connections"}
    attr = [{"feature": "ct_dst_ltm", "value": 40, "baseline": 3, "z": 4.0}]
    anomalies = [_anom("2.2.2.2", sig, attr) for _ in range(6)]

    h = eng._behavioral_hypothesis("2.2.2.2", anomalies, alerts=[])

    assert h is not None
    assert "T1046" in h.confirmed_evidence[0]["text"]
    assert h.confidence >= 0.6
    assert h.signature["mitre_id"] == "T1046"
    assert "explained_signature" in h.score_breakdown


def test_behavioral_hypothesis_fallback_when_no_signature():
    eng = RCAEngine(TopologyGraph())
    sig = {"label": "anomalous volumetric pattern", "mitre_id": "", "mitre_name": "",
           "matched_features": ["dttl"], "sentence": "abnormal deviation in dttl"}
    attr = [{"feature": "dttl", "value": 9, "baseline": 30, "z": -1.4}]
    anomalies = [_anom("2.2.2.2", sig, attr) for _ in range(6)]

    h = eng._behavioral_hypothesis("2.2.2.2", anomalies, alerts=[])
    assert h.confidence < 0.5
    assert "Unexplained" in h.root_cause
