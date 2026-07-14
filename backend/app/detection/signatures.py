"""Interpretable translation layer: map Isolation-Forest feature attribution to a
named behavioral signature anchored in MITRE ATT&CK. This is NOT a detector — the
ML (Isolation Forest / Kitsune) detects; these rules turn its output into analyst
language + a threat-taxonomy id."""
from __future__ import annotations


def _z(attr: list[dict], feature: str) -> float:
    for a in attr:
        if a["feature"] == feature:
            return float(a["z"])
    return 0.0


def _sig(label, mitre_id, mitre_name, feats, sentence) -> dict:
    return {"label": label, "mitre_id": mitre_id, "mitre_name": mitre_name,
            "matched_features": feats, "sentence": sentence}


def classify(attribution: list[dict]) -> dict:
    z = lambda f: _z(attribution, f)

    # DoS / flood: many packets + high load, very short flows, source fan-out.
    if (z("Spkts") > 2 or z("Sload") > 2) and z("dur") < -0.5:
        return _sig("DoS / flood", "T1498", "Network Denial of Service",
                    ["Spkts", "Sload", "dur"],
                    "high packet/load volume in very short-lived flows")

    # Reflection / amplification: response bytes hugely exceed request bytes.
    if z("dbytes") > 2 and z("sbytes") <= 0.5:
        return _sig("reflection / amplification", "T1498.002", "Reflection Amplification",
                    ["dbytes", "sbytes"],
                    "response payload far exceeds the request payload")

    # Data exfiltration: large/steady outbound bytes over longer flows.
    if (z("sbytes") > 2 or z("smeansz") > 2 or z("Sload") > 2) and z("dur") > 0.5:
        return _sig("data exfiltration", "T1041", "Exfiltration Over C2 Channel",
                    ["sbytes", "smeansz", "dur"],
                    "sustained large outbound transfer over an extended flow")

    # Port / host scan: high destination/service fan-out, near-zero payload, short.
    if (z("ct_dst_ltm") > 1.5 or z("ct_srv_dst") > 1.5) and z("sbytes") <= 0.5:
        return _sig("port/host scan", "T1046", "Network Service Discovery",
                    ["ct_dst_ltm", "ct_srv_dst", "sbytes"],
                    "many short connections with minimal payload across destinations")

    # Beaconing / C2: repeated same-service contact with small payloads.
    if z("ct_srv_dst") > 1.5 and abs(z("sbytes")) < 1.0:
        return _sig("beaconing / C2", "T1071", "Application Layer Protocol",
                    ["ct_srv_dst"],
                    "repeated same-service contact consistent with C2 beaconing")

    feats = [a["feature"] for a in attribution[:3]] or ["flow statistics"]
    return _sig("anomalous volumetric pattern", "", "", feats,
                "abnormal deviation in " + ", ".join(feats))
