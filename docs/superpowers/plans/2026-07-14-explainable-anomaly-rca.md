# Explainable Anomaly RCA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn "Unexplained traffic-flow anomaly (20%)" incidents into named, MITRE-tagged, evidence-backed behavioral signatures with faithful per-feature attribution and honest confidence.

**Architecture:** Carry per-feature attribution (z-scores from the already-fitted StandardScaler) out of the Isolation Forest, classify it into a behavioral signature mapped to MITRE ATT&CK, embed both into the anomaly event and then the RCA hypothesis, and render them in the frontend hypothesis card. No new backend endpoint and no new dependency for the core; SHAP is an optional stretch with graceful fallback to the z-score attribution.

**Tech Stack:** Python 3.12, scikit-learn (IsolationForest already present), FastAPI, pytest; Next.js (frontend), React, Tailwind.

## Global Constraints

- No mock/hardcoded/simulated data — attribution derives from real scored flows only.
- Backend venv is python3.12 at `backend/.venv`; run pytest via `backend/.venv/bin/python -m pytest`.
- Disk budget ~12GB free — do NOT add heavy deps in the core; SHAP (Task 7) is optional and must degrade gracefully if absent.
- Every score component stays named and additive (spec: confidence must be explainable/decomposable).
- Frontend: this is a modified Next.js — read `frontend/node_modules/next/dist/docs/` before writing/altering any Next-specific code. The change here is a plain React component edit, no Next APIs.

---

### Task 1: Per-feature attribution in the Isolation Forest

**Files:**
- Modify: `backend/app/detection/isolation_forest.py`
- Test: `backend/tests/test_attribution.py` (create)

**Interfaces:**
- Produces: `FlowAnomalyDetector.score(df)` returns df with a new `attribution` column: `list[dict]` per row, each dict `{"feature": str, "value": float, "baseline": float, "z": float}`, top-5 by |z|, only features with |z| >= 1.0, most-deviating first.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_attribution.py
import numpy as np
import pandas as pd
from app.detection.isolation_forest import FlowAnomalyDetector


def _normal_frame(n=500):
    rng = np.random.default_rng(0)
    feats = FlowAnomalyDetector().features
    data = {f: rng.normal(10.0, 1.0, n) for f in feats}
    return pd.DataFrame(data)


def test_attribution_flags_the_deviating_feature():
    det = FlowAnomalyDetector(contamination=0.02)
    train = _normal_frame()
    det.fit(train)

    outlier = _normal_frame(1)
    outlier.loc[0, "sbytes"] = 5000.0  # massively above the ~10 baseline
    scored = det.score(outlier)

    attr = scored.iloc[0]["attribution"]
    assert isinstance(attr, list) and len(attr) >= 1
    top = attr[0]
    assert top["feature"] == "sbytes"
    assert top["z"] > 3.0
    assert abs(top["baseline"] - 10.0) < 1.5
    assert top["value"] == 5000.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_attribution.py -v`
Expected: FAIL — `KeyError: 'attribution'` (column not produced yet).

- [ ] **Step 3: Implement attribution in the detector**

Add this method to `FlowAnomalyDetector` (after `_matrix`), and set the column at the end of `score`:

```python
    def _attribution(self, x_scaled: np.ndarray, raw: pd.DataFrame, k: int = 5) -> list[list[dict]]:
        """Per-row top-k deviating features. Scaled values ARE z-scores vs the
        fitted normal baseline (StandardScaler mean/scale), so this is a free,
        honest 'which features are abnormal' signal."""
        mean = self.scaler.mean_
        raw_vals = self._matrix(raw)
        out: list[list[dict]] = []
        for i in range(x_scaled.shape[0]):
            z = x_scaled[i]
            order = np.argsort(-np.abs(z))
            items: list[dict] = []
            for j in order[:k]:
                if abs(z[j]) < 1.0:
                    continue
                items.append({
                    "feature": self.features[j],
                    "value": round(float(raw_vals[i][j]), 4),
                    "baseline": round(float(mean[j]), 4),
                    "z": round(float(z[j]), 2),
                })
            out.append(items)
        return out
```

In `score`, after `out["is_anomaly"] = ...`, add:

```python
        out["attribution"] = self._attribution(x, df)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_attribution.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/detection/isolation_forest.py backend/tests/test_attribution.py
git commit -m "feat(detector): per-feature baseline-deviation attribution on scored flows"
```

---

### Task 2: Behavioral signature classifier with MITRE ATT&CK mapping

**Files:**
- Create: `backend/app/detection/signatures.py`
- Test: `backend/tests/test_signatures.py` (create)

**Interfaces:**
- Consumes: attribution list from Task 1 (`[{"feature","value","baseline","z"}]`).
- Produces: `classify(attribution: list[dict]) -> dict` with keys `label, mitre_id, mitre_name, matched_features (list[str]), sentence`. When nothing matches, returns a fallback dict with `mitre_id == ""` and label `"anomalous volumetric pattern"`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_signatures.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_signatures.py -v`
Expected: FAIL — `ModuleNotFoundError: app.detection.signatures`.

- [ ] **Step 3: Implement the classifier**

```python
# backend/app/detection/signatures.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_signatures.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/detection/signatures.py backend/tests/test_signatures.py
git commit -m "feat(detection): behavioral signature classifier with MITRE ATT&CK mapping"
```

---

### Task 3: Attach attribution + signature to anomaly events

**Files:**
- Modify: `backend/app/detection/isolation_forest.py` (`anomaly_event_from_flow`)
- Test: `backend/tests/test_anomaly_event.py` (create)

**Interfaces:**
- Consumes: scored row with `attribution` (Task 1), `classify` (Task 2).
- Produces: `anomaly_event_from_flow(row)` sets `event.attributes["attribution"]` (list[dict]) and `event.attributes["signature"]` (dict from `classify`).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_anomaly_event.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_anomaly_event.py -v`
Expected: FAIL — `KeyError: 'signature'`.

- [ ] **Step 3: Implement**

In `isolation_forest.py`, add import near the top:

```python
from .signatures import classify as classify_signature
```

In `anomaly_event_from_flow`, compute attribution/signature and add them to the `attributes` dict:

```python
    attribution = row.get("attribution")
    if not isinstance(attribution, list):
        attribution = []
    signature = classify_signature(attribution)
```

Then in the `attributes={...}` dict of the returned `Event`, add:

```python
            "attribution": attribution,
            "signature": signature,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_anomaly_event.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/detection/isolation_forest.py backend/tests/test_anomaly_event.py
git commit -m "feat(detector): carry attribution + MITRE signature on anomaly events"
```

---

### Task 4: RCA engine — explained behavioral hypothesis

**Files:**
- Modify: `backend/app/rca/scoring.py` (add two weights)
- Modify: `backend/app/rca/engine.py` (add fields to `Hypothesis`; replace `_load_hypothesis` with `_behavioral_hypothesis`; add helpers; update the call site)
- Test: `backend/tests/test_behavioral_hypothesis.py` (create)

**Interfaces:**
- Consumes: anomaly `Event`s whose `.attributes` carry `signature` + `attribution` (Task 3).
- Produces: `Hypothesis` dataclass gains `signature: dict` and `attribution: list[dict]` fields (default empty). `RCAEngine._behavioral_hypothesis(node, anomalies, alerts)` returns a `Hypothesis` with non-empty `confirmed_evidence`, confidence ~0.65 when a MITRE signature is present, ~0.35 on fallback.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_behavioral_hypothesis.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_behavioral_hypothesis.py -v`
Expected: FAIL — `AttributeError: 'RCAEngine' object has no attribute '_behavioral_hypothesis'`.

- [ ] **Step 3a: Add weights to `scoring.py`**

After `W_INDEPENDENT_SIGNAL = 10` add:

```python
W_EXPLAINED_SIGNATURE = 30     # a named behavioral signature (MITRE-mapped) matched the anomaly
W_FEATURE_ATTRIBUTION = 15     # specific deviating features named from the detector
```

- [ ] **Step 3b: Add fields to the `Hypothesis` dataclass in `engine.py`**

In the `Hypothesis` dataclass, after `explanation: str = ""` add:

```python
    signature: dict = field(default_factory=dict)
    attribution: list[dict] = field(default_factory=list)
```

- [ ] **Step 3c: Update the scoring import in `engine.py`**

Change the import block from `.scoring` to also pull the two new weights:

```python
from .scoring import (
    W_CONFIG_WITHIN_WINDOW, W_CONFIRMED_MATCH, W_DIRECT_UPSTREAM_DEP,
    W_EXPLAINED_SIGNATURE, W_FEATURE_ATTRIBUTION,
    W_HISTORICAL_MATCH, W_INDEPENDENT_SIGNAL, W_MATCHING_PROPAGATION,
    EvidenceItem, EvidenceKind, Recommendation, RiskTier, ScoreBreakdown,
)
```

- [ ] **Step 3d: Replace `_load_hypothesis` with `_behavioral_hypothesis` + helpers**

Replace the entire `_load_hypothesis` method with:

```python
    def _behavioral_hypothesis(self, node, anomalies, alerts):
        # only when anomalies exist without a clearer (config/attack/upstream) cause
        if not anomalies or alerts:
            return None
        labels: dict[str, int] = defaultdict(int)
        sig_by_label: dict[str, dict] = {}
        all_attr: list[dict] = []
        for e in anomalies:
            sig = e.attributes.get("signature") or {}
            attr = e.attributes.get("attribution") or []
            all_attr.extend(attr)
            if sig.get("label"):
                labels[sig["label"]] += 1
                sig_by_label[sig["label"]] = sig

        top_sig = sig_by_label.get(max(labels, key=labels.get)) if labels else {}
        explained = bool(top_sig.get("mitre_id"))
        top_feats = self._aggregate_attribution(all_attr, k=4)

        sb = ScoreBreakdown()
        confirmed, correlated, missing = [], [], []

        if explained:
            sb.add("explained_signature", W_EXPLAINED_SIGNATURE)
            confirmed.append(_ev_item(EvidenceKind.CONFIRMED,
                f"{labels[top_sig['label']]} flow(s) match a {top_sig['label']} pattern "
                f"(MITRE {top_sig['mitre_id']} · {top_sig['mitre_name']}): {top_sig['sentence']}.",
                source="signature_classifier", component="explained_signature"))
        if top_feats:
            sb.add("feature_attribution", W_FEATURE_ATTRIBUTION)
            feat_txt = ", ".join(
                f"{f['feature']} {f['z']:+.1f}σ (obs {f['value']} vs baseline {f['baseline']})"
                for f in top_feats)
            confirmed.append(_ev_item(EvidenceKind.CONFIRMED,
                f"Isolation Forest attribution — deviations from learned-normal baseline: {feat_txt}.",
                source="isolation_forest", component="feature_attribution"))

        sb.add("independent_corroboration", W_INDEPENDENT_SIGNAL)
        sb.add("volumetric_pattern", W_MATCHING_PROPAGATION // 2)
        correlated.append(_ev_item(EvidenceKind.CORRELATED,
            f"{len(anomalies)} statistically anomalous flows on {node} (unsupervised detector).",
            source="isolation_forest"))
        missing.append(_ev_item(EvidenceKind.MISSING,
            f"Host-level telemetry (CPU/memory/bandwidth) for {node} is unavailable to confirm impact.",
            source="telemetry"))

        root_cause = (f"{top_sig['label'].title()} on {node}" if explained
                      else f"Unexplained traffic-flow anomaly on {node}")
        recs = self._signature_recommendations(node, top_sig, explained)
        return Hypothesis(
            root_cause=root_cause, kind="behavioral_anomaly",
            confidence=sb.confidence, score_breakdown=sb.components,
            confirmed_evidence=confirmed, correlated_signals=correlated,
            missing_evidence=missing, recommendations=recs,
            signature=top_sig or {}, attribution=top_feats)

    def _aggregate_attribution(self, all_attr: list[dict], k: int = 4) -> list[dict]:
        agg: dict[str, dict] = {}
        for a in all_attr:
            cur = agg.get(a["feature"])
            if cur is None or abs(a["z"]) > abs(cur["z"]):
                agg[a["feature"]] = a
        return sorted(agg.values(), key=lambda a: abs(a["z"]), reverse=True)[:k]

    def _signature_recommendations(self, node, sig, explained):
        if not explained:
            return [asdict(Recommendation(f"Run network diagnostics on {node}", RiskTier.DIAGNOSTIC,
                    "Anomalous flow statistics without a confirmed root cause."))]
        mid = sig.get("mitre_id", "")
        if mid == "T1046":
            action = f"Rate-limit and inspect scanning sources reaching {node}"
        elif mid in ("T1498", "T1498.002"):
            action = f"Engage upstream DDoS scrubbing / rate-limiting for {node}"
        elif mid == "T1041":
            action = f"Inspect egress from {node} and apply DLP/egress filtering"
        elif mid == "T1071":
            action = f"Block suspected C2 endpoints and inspect beaconing flows to {node}"
        else:
            action = f"Investigate anomalous flows on {node}"
        return [
            asdict(Recommendation(action, RiskTier.LOW_RISK,
                   f"Behavioral signature '{sig['label']}' ({mid}) matched the anomalous flows.")),
            asdict(Recommendation(f"Capture host telemetry on {node}", RiskTier.DIAGNOSTIC,
                   "Confirm impact and close the missing-evidence gap before enforcement.")),
        ]
```

- [ ] **Step 3e: Update the call site in `build_incident`**

Change the line `h_load = self._load_hypothesis(focal_node, anomalies, alerts)` to:

```python
        h_load = self._behavioral_hypothesis(focal_node, anomalies, alerts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_behavioral_hypothesis.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/rca/scoring.py backend/app/rca/engine.py backend/tests/test_behavioral_hypothesis.py
git commit -m "feat(rca): explained behavioral hypothesis with MITRE signature + attribution"
```

---

### Task 5: Frontend types + hypothesis card rendering (signature badge + attribution)

**Files:**
- Modify: `frontend/src/lib/types.ts` (extend `Hypothesis`)
- Modify: `frontend/src/components/IncidentDetail.tsx` (`HypothesisCard`)

**Interfaces:**
- Consumes: `Hypothesis.signature` (`{label,mitre_id,mitre_name,matched_features,sentence}`) and `Hypothesis.attribution` (`{feature,value,baseline,z}[]`) from Task 4.
- Produces: hypothesis card shows a MITRE badge (when `mitre_id`) and a compact per-feature deviation bar list.

- [ ] **Step 1: Extend the `Hypothesis` type**

In `frontend/src/lib/types.ts`, add to the `Hypothesis` interface (after `explanation?: string;`):

```typescript
  signature?: {
    label: string;
    mitre_id: string;
    mitre_name: string;
    matched_features: string[];
    sentence: string;
  };
  attribution?: { feature: string; value: number; baseline: number; z: number }[];
```

- [ ] **Step 2: Render the signature + attribution in `HypothesisCard`**

In `frontend/src/components/IncidentDetail.tsx`, inside `HypothesisCard`, immediately after the closing `</div>` of the `score_breakdown` chips block (the `<div className="mb-3 flex flex-wrap gap-1.5">…</div>`), insert:

```tsx
      {h.signature?.mitre_id && (
        <div className="mb-3 flex items-center gap-2">
          <span className="mono rounded bg-[#3a1d1d] px-1.5 py-0.5 text-[10px] font-bold text-[#f87171]">
            MITRE {h.signature.mitre_id}
          </span>
          <span className="text-[11px] text-[#c6d4e6]">{h.signature.mitre_name}</span>
        </div>
      )}
      {h.attribution && h.attribution.length > 0 && (
        <div className="mb-3">
          <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-[var(--muted)]">
            Why this flow is anomalous — feature attribution
          </div>
          <div className="space-y-1">
            {h.attribution.map((a) => {
              const mag = Math.min(100, Math.abs(a.z) * 20);
              const up = a.z >= 0;
              return (
                <div key={a.feature} className="flex items-center gap-2 text-[11px]">
                  <span className="mono w-28 shrink-0 text-[#9fb4cc]">{a.feature}</span>
                  <div className="relative h-2 flex-1 rounded bg-[#0b111b]">
                    <div
                      className="absolute top-0 h-2 rounded"
                      style={{ width: `${mag}%`, background: up ? "#f97316" : "#38bdf8" }}
                    />
                  </div>
                  <span className="mono w-32 shrink-0 text-right text-[#c6d4e6]">
                    {a.z >= 0 ? "+" : ""}{a.z}σ · obs {a.value}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
```

- [ ] **Step 3: Verify the frontend builds**

Run: `cd frontend && npx tsc --noEmit`
Expected: no type errors. (If the project uses a different check, run `npm run lint` / `npm run build` as available.)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/types.ts frontend/src/components/IncidentDetail.tsx
git commit -m "feat(ui): show MITRE signature badge + feature-attribution bars on hypotheses"
```

---

### Task 6: End-to-end verification on real data

**Files:**
- None modified — this is a verification task.

- [ ] **Step 1: Run the full backend test suite**

Run: `cd backend && .venv/bin/python -m pytest tests/ -v`
Expected: all tests PASS.

- [ ] **Step 2: Drive the real pipeline and confirm an explained hypothesis**

Run this script against the real datasets (no mocks) to confirm the give-up branch now explains:

```bash
cd backend && .venv/bin/python -c "
from app.pipeline import Pipeline
import pandas as pd
p = Pipeline(); info = p.prepare(limit=8000)
rows = p._replay_rows
anoms = rows[rows['is_anomaly'] == 1].head(200)
from app.detection.isolation_forest import anomaly_event_from_flow
events = [anomaly_event_from_flow(r) for _, r in anoms.iterrows()]
# group by node, pick the busiest
from collections import Counter
node = Counter(e.node for e in events).most_common(1)[0][0]
node_events = [e for e in events if e.node == node]
h = p.rca._behavioral_hypothesis(node, node_events, alerts=[])
print('node', node, 'n', len(node_events))
print('root_cause:', h.root_cause)
print('confidence:', h.confidence)
print('signature:', h.signature.get('mitre_id'), h.signature.get('label'))
print('confirmed[0]:', h.confirmed_evidence[0]['text'] if h.confirmed_evidence else None)
"
```

Expected: prints a real focal node, a confidence noticeably above 0.20 (typically ~0.35–0.65), a signature label, and a non-empty confirmed-evidence line naming real deviating features. Record the actual output.

- [ ] **Step 3: Commit any doc/notes if needed** (no code change expected)

```bash
git commit --allow-empty -m "test: verify explained behavioral hypotheses on real UNSW flows"
```

---

### Task 7 (OPTIONAL / STRETCH): SHAP faithful attribution endpoint

> Only attempt if disk allows installing `shap` and time remains. The core (Tasks 1–6)
> already renders faithful baseline-deviation attribution; this upgrades the numbers to
> model-faithful SHAP values and MUST degrade to the Task-1 attribution on any failure.

**Files:**
- Modify: `backend/app/main.py` (add `GET /api/incidents/{id}/attribution`)
- Modify: `backend/app/pipeline.py` (add `shap_attribution(node)` helper)
- Test: `backend/tests/test_shap_endpoint.py` (create)

**Interfaces:**
- Produces: `GET /api/incidents/{incident_id}/attribution` → `{ "method": "shap" | "baseline_deviation", "features": [{feature, contribution, value, baseline}], "signature": {...} }`.

- [ ] **Step 1: Attempt install (bounded)**

Run: `cd backend && .venv/bin/python -m pip install "shap>=0.44" 2>&1 | tail -3 && df -h . | tail -1`
If it fails or disk is tight, SKIP the install — the endpoint's fallback path below still works.

- [ ] **Step 2: Write the failing test (fallback path, no shap required)**

```python
# backend/tests/test_shap_endpoint.py
from app.pipeline import Pipeline


def test_attribution_helper_returns_features():
    p = Pipeline(); p.prepare(limit=4000)
    rows = p._replay_rows
    node = rows[rows["is_anomaly"] == 1]["dstip"].value_counts().index[0]
    res = p.shap_attribution(node)
    assert res["method"] in ("shap", "baseline_deviation")
    assert isinstance(res["features"], list) and len(res["features"]) >= 1
    assert {"feature", "contribution"} <= set(res["features"][0].keys())
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_shap_endpoint.py -v`
Expected: FAIL — `AttributeError: 'Pipeline' object has no attribute 'shap_attribution'`.

- [ ] **Step 4: Implement `shap_attribution` on `Pipeline`**

```python
    def shap_attribution(self, node: str, max_rows: int = 50) -> dict:
        """Model-faithful SHAP attribution for a node's anomalous flows, with a
        graceful fallback to baseline-deviation attribution if shap is unavailable."""
        rows = self._replay_rows
        if rows is None:
            return {"method": "baseline_deviation", "features": [], "signature": {}}
        sub = rows[(rows["dstip"] == node) & (rows["is_anomaly"] == 1)].head(max_rows)
        if sub.empty:
            sub = rows[rows["dstip"] == node].head(max_rows)
        feats = self.detector.features
        from .detection.signatures import classify as _classify
        # signature from the strongest row's attribution
        attr0 = sub.iloc[0].get("attribution") if len(sub) else []
        signature = _classify(attr0 if isinstance(attr0, list) else [])
        try:
            import shap  # optional
            x = self.detector.scaler.transform(self.detector._matrix(sub))
            explainer = shap.TreeExplainer(self.detector.model)
            vals = explainer.shap_values(x)
            import numpy as np
            mean_abs = np.abs(vals).mean(axis=0)
            order = np.argsort(-mean_abs)[:8]
            mean_raw = self.detector.scaler.mean_
            raw = self.detector._matrix(sub).mean(axis=0)
            features = [{"feature": feats[j], "contribution": round(float(mean_abs[j]), 4),
                         "value": round(float(raw[j]), 4), "baseline": round(float(mean_raw[j]), 4)}
                        for j in order]
            return {"method": "shap", "features": features, "signature": signature}
        except Exception:
            # fallback: aggregate the baseline-deviation attribution we already compute
            agg: dict[str, dict] = {}
            for _, r in sub.iterrows():
                for a in (r.get("attribution") or []):
                    cur = agg.get(a["feature"])
                    if cur is None or abs(a["z"]) > abs(cur["z"]):
                        agg[a["feature"]] = a
            features = [{"feature": a["feature"], "contribution": round(abs(a["z"]), 4),
                         "value": a["value"], "baseline": a["baseline"]}
                        for a in sorted(agg.values(), key=lambda a: abs(a["z"]), reverse=True)[:8]]
            return {"method": "baseline_deviation", "features": features, "signature": signature}
```

- [ ] **Step 5: Add the endpoint in `main.py`**

Near the other incident routes, add (uses the module-level `pipeline` instance already present in `main.py` — match the existing name):

```python
@api.get("/api/incidents/{incident_id}/attribution")
async def incident_attribution(incident_id: str) -> dict:
    inc = await store.get_incident(incident_id)
    if not inc:
        raise HTTPException(404, "incident not found")
    return await asyncio.to_thread(pipeline.shap_attribution, inc["focal_node"])
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_shap_endpoint.py -v`
Expected: PASS (method is `shap` if installed, else `baseline_deviation`).

- [ ] **Step 7: Commit**

```bash
git add backend/app/pipeline.py backend/app/main.py backend/tests/test_shap_endpoint.py
git commit -m "feat(explainability): optional SHAP attribution endpoint with graceful fallback"
```

---

## Self-Review

- **Spec coverage:** Component 1 (attribution) → Task 1; Component 2 (signatures + MITRE) → Task 2; wiring → Task 3; Component 3 (engine + scoring) → Task 4; Component 4 (frontend explainability + SHAP) → Tasks 5 (render) + 7 (SHAP endpoint). Honesty (labeled method, missing-evidence retained) covered in Tasks 4/7. Real-data verification → Task 6. No gaps.
- **Placeholder scan:** No TBD/TODO; every code step shows full code and exact commands.
- **Type consistency:** `attribution` dict keys `{feature,value,baseline,z}` consistent across Tasks 1/3/4/5/7. `signature` keys `{label,mitre_id,mitre_name,matched_features,sentence}` consistent across Tasks 2/3/4/5. `_behavioral_hypothesis` / `_aggregate_attribution` / `_signature_recommendations` / `shap_attribution` names consistent between definition and call sites. Call-site rename in Task 4 Step 3e matches the method defined in 3d.

## Notes / assumptions to verify at execution time

- `main.py` exposes a module-level pipeline object; confirm its variable name before Task 7 Step 5 and match it.
- `backend/tests/` may need an `__init__.py` or a `conftest.py` adding `app` to the path; if `import app...` fails, add `backend/conftest.py` with `import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).parent))` (backend dir is the package root via `pyproject`). Run pytest from `backend/`.
