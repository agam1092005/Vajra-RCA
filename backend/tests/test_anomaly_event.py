import pandas as pd
from app.detection.isolation_forest import anomaly_event_from_flow


def test_event_carries_attribution_and_signature():
    row = pd.Series({
        "srcip": "1.1.1.1", "dstip": "2.2.2.2", "dsport_i": 80, "service": "http",
        "Stime": 100.0, "anomaly_score": 0.2, "Label": 1, "attack_cat": "",
        "attribution": [
            {"feature": "ct_dst_ltm", "value": 40, "baseline": 3, "z": 4.0},
            {"feature": "sbytes", "value": 1, "baseline": 500, "z": -1.6},
        ],
    })
    ev = anomaly_event_from_flow(row)
    assert ev.attributes["signature"]["mitre_id"] == "T1046"
    assert ev.attributes["attribution"][0]["feature"] == "ct_dst_ltm"
