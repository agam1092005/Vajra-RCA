from app.detection.signatures import classify


def _a(**zs):
    return [{"feature": f, "value": 0.0, "baseline": 0.0, "z": z} for f, z in zs.items()]


def test_port_scan_signature():
    sig = classify(_a(ct_dst_ltm=4.0, ct_srv_dst=3.0, sbytes=-1.5, dur=-1.2))
    assert sig["label"] == "port/host scan"
    assert sig["mitre_id"] == "T1046"


def test_exfiltration_signature():
    sig = classify(_a(sbytes=5.0, smeansz=3.0, dur=2.5))
    assert sig["mitre_id"] == "T1041"


def test_dos_flood_signature():
    sig = classify(_a(Spkts=6.0, Sload=5.0, dur=-2.0, ct_src_ltm=3.0))
    assert sig["mitre_id"] == "T1498"


def test_fallback_when_no_pattern():
    sig = classify(_a(dttl=1.2))
    assert sig["mitre_id"] == ""
    assert sig["label"] == "anomalous volumetric pattern"
    assert "dttl" in sig["matched_features"]
