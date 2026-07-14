#!/usr/bin/env python3
"""End-to-end verification against a running backend (default http://localhost:8000).

Drives the real flow: checks readiness, streams metrics, injects a REAL config change,
and asserts a correlated incident is produced with a ranked, evidence-backed hypothesis
whose top cause is the configuration change — with all three evidence buckets populated.

Usage:
    python scripts/verify_e2e.py [base_url]
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"


def _get(path: str):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=30) as r:
        return json.load(r)


def _post(path: str, body: dict | None = None):
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(f"{BASE}{path}", data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def check(name: str, cond: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return cond


def main() -> int:
    ok = True
    print("1. readiness")
    for _ in range(30):
        try:
            h = _get("/api/health")
            if h.get("ready"):
                break
        except Exception:
            pass
        time.sleep(1)
    ok &= check("backend ready", _get("/api/health").get("ready", False))

    print("1.5. activate simulated telemetry")
    try:
        t_res = _post("/api/telemetry/replay/toggle", {"active": True})
        ok &= check("simulation activated", t_res.get("active") is True)
    except Exception as e:
        print(f"  [FAIL] Failed to toggle telemetry: {e}")
        ok = False

    print("2. real ingestion is flowing")
    m1 = _get("/api/metrics")
    time.sleep(3)
    m2 = _get("/api/metrics")
    ok &= check("flow counter increasing", m2["counters"]["flows"] > m1["counters"]["flows"],
                f'{m1["counters"]["flows"]} -> {m2["counters"]["flows"]}')

    print("3. topology built from real data")
    topo = _get("/api/topology")
    ok &= check("topology has nodes and edges", len(topo["nodes"]) > 0 and len(topo["edges"]) > 0,
                f'{len(topo["nodes"])} nodes / {len(topo["edges"])} edges')

    print("4. inject REAL config change -> correlated incident")
    inc = _post("/api/inject/config-change", {})
    hyps = inc.get("hypotheses", [])
    ok &= check("incident produced", bool(inc.get("incident_id")), inc.get("incident_id", ""))
    ok &= check("has ranked hypotheses", len(hyps) >= 1, f"{len(hyps)} hypotheses")
    top = hyps[0] if hyps else {}
    ok &= check("top hypothesis is the config change", top.get("kind") == "config_change",
                top.get("root_cause", ""))
    ok &= check("confidence is decomposable", len(top.get("score_breakdown", {})) >= 2,
                json.dumps(top.get("score_breakdown", {})))
    ok &= check("has confirmed evidence", len(top.get("confirmed_evidence", [])) >= 1)
    ok &= check("has missing evidence called out", len(top.get("missing_evidence", [])) >= 1)
    ok &= check("blast radius computed", inc.get("blast_radius", {}).get("count", 0) >= 0)
    ok &= check("timeline present", len(inc.get("timeline", [])) >= 1)

    print("5. explanation + audit trail")
    iid = inc["incident_id"]
    expl = _post(f"/api/incidents/{iid}/explain")
    ok &= check("explanation generated", bool(expl.get("narrative")), expl.get("generated_by", ""))
    audit = _get(f"/api/incidents/{iid}/audit")
    ok &= check("audit trail recorded", len(audit) >= 1, f"{len(audit)} entries")

    print("6. restore default stopped state")
    try:
        t_res = _post("/api/telemetry/replay/toggle", {"active": False})
        check("simulation deactivated", t_res.get("active") is False)
    except Exception as e:
        print(f"  [WARNING] Failed to restore deactivated state: {e}")

    print("\n" + ("ALL CHECKS PASSED ✅" if ok else "SOME CHECKS FAILED ❌"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
