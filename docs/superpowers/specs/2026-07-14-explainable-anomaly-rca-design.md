# Explainable Anomaly RCA — Design Spec

**Date:** 2026-07-14
**Status:** Approved (build to win)
**Problem it fixes:** Incidents render as "Unexplained traffic-flow anomaly on <ip>" at a
flat 20% confidence with an empty Confirmed-evidence column. The system detects that a flow
is abnormal but never explains *why*, so the top hypothesis reads as a shrug.

## Root cause of the "unexplained" behavior

1. **The detector emits a scalar, not a reason.** `isolation_forest.py:score()` attaches a
   single `anomaly_score`. `anomaly_event_from_flow()` carries the score but no feature-level
   detail. All "which features are weird" information is discarded at detection time.
2. **The RCA engine has a give-up branch.** `engine.py:_load_hypothesis()` fires only when
   config / attack / upstream hypotheses all miss. It emits a hardcoded string, no confirmed
   evidence, and a fixed score of `W_INDEPENDENT_SIGNAL (10) + W_MATCHING_PROPAGATION//2 (10)
   = 20/100`. Every such incident therefore reads exactly 20%.

## Goal

Carry feature-level attribution through the whole chain and add an interpretable signature
layer, so the give-up branch becomes a real, evidence-backed, honestly-scored hypothesis that
names the probable behavior (port scan, exfil, DoS, beaconing…), maps it to MITRE ATT&CK, and
shows a faithful per-feature explanation.

## Design principles (what makes it industry-grade)

- **Faithful attribution leads; proxy degrades.** SHAP (faithful to the model) is the primary
  explanation surface. Baseline-deviation z-scores (a cheap proxy, computed for free from the
  fitted `StandardScaler`) are the always-available fallback so the UI never renders empty.
- **The rules are a *translation* layer, not the detector.** The detectors stay ML (Isolation
  Forest + the online Kitsune autoencoder). The signature rules only turn ML output into
  analyst language + a threat-taxonomy label. Framed and labeled as such.
- **Honesty preserved.** Signatures are labeled "probable." Missing-evidence stays visible.
  Every score component remains named and additive. Nothing uncertain is shown as conclusion.

## Components

### 1. Feature attribution in the detector — `detection/isolation_forest.py`
- The fitted `StandardScaler` gives per-feature z = (x − mean) / scale for free; the scaled
  matrix already computed in `score()` *is* the z-score matrix.
- For each anomalous row, attach top-k (k=5) deviating features as
  `attribution: [{feature, value, baseline, z}]`, ranked by |z|.
- Surface via `anomaly_event_from_flow()` into `event.attributes["attribution"]`.
- No new dependencies; vectorized; runs inside existing `score()`.

### 2. Behavioral signature classifier — new `detection/signatures.py`
- Pure function: `classify(attribution, raw_row) -> Signature`.
- `Signature = {label, mitre_id, mitre_name, matched_features, sentence, base_points}`.
- Rules over real UNSW features:
  - **Port/host scan** → high `ct_dst_ltm`/`ct_srv_dst`, near-zero `sbytes`+`dbytes`, short
    `dur` → MITRE **T1046** (Network Service Discovery).
  - **Data exfiltration** → high `sbytes`/`Sload`/`smeansz`, long `dur`, low `dbytes` →
    **T1041** (Exfiltration Over C2 Channel).
  - **DoS / flood** → very high `Spkts`+`Sload`, tiny `dur`, high `ct_src_ltm` → **T1498**
    (Network Denial of Service).
  - **Reflection / amplification** → `dbytes` ≫ `sbytes` → **T1498.002**.
  - **Beaconing / C2** → regular inter-packet timing (low `Sjit`/`Dintpkt` variance) + small
    payload + elevated `ct_dst_ltm` → **T1071** (Application Layer Protocol).
  - **Fallback** → "anomalous volumetric pattern" naming top-3 features; no MITRE id.
- Attach `signature` dict to `event.attributes["signature"]` in `anomaly_event_from_flow()`.

### 3. RCA engine upgrade — `engine.py`, `scoring.py`
- Rename `_load_hypothesis` → `_behavioral_hypothesis`.
- Aggregate the signature across the focal node's anomalies (majority label; collect the
  strongest attribution examples).
- New named score components in `scoring.py`:
  - `W_EXPLAINED_SIGNATURE = 30` — a signature matched with real deviating features.
  - `W_FEATURE_ATTRIBUTION = 15` — top deviating features named and consistent.
- Emit **confirmed evidence** (previously empty): e.g. *"6 flows match a port-scan pattern
  (MITRE T1046): ct_dst_ltm 12× baseline, payload near-zero, dur 0.02s."*
- Confidence now lands ~45–70% for explained anomalies instead of the flat 20% cap; falls
  back to ~20% only when nothing matches (fallback signature).
- Signature-specific recommendations (scan → rate-limit/block source; exfil → inspect egress
  & DLP; DoS → upstream scrubbing). Keep the honest Missing-evidence line.

### 4. SHAP "Explainability" tab — backend endpoint + `frontend/src/components/IncidentDetail.tsx`
- Backend endpoint `GET /api/incidents/{id}/explain`:
  - Take the focal node's anomalous flows (bounded N, e.g. ≤ 50).
  - Run `shap.TreeExplainer` on the Isolation Forest over those rows → mean |SHAP| per feature.
  - **Graceful degrade:** on any import/compute failure, return the z-score attribution
    (already computed) with `method: "baseline_deviation"` instead of `method: "shap"`.
  - Response: `{ method, features: [{feature, contribution, value, baseline}], signature }`.
- Frontend: add an "Explainability" tab to `IncidentDetail` showing a horizontal
  feature-contribution bar chart + the MITRE badge. Chart built per the `dataviz` skill,
  theme-aware, with a clear label of which method produced it (SHAP vs baseline-deviation).

## Data flow (end to end)

```
score()  ── attach attribution (z-scores) per anomalous row
   │
anomaly_event_from_flow()  ── attribution + signature (MITRE) into event.attributes
   │
window / correlation  ── events reach the focal node
   │
_behavioral_hypothesis()  ── aggregate signature → confirmed evidence + real confidence
   │
final_report → UI  ── signature + MITRE inline, Explainability tab (SHAP → z-score fallback)
```

## Non-goals (YAGNI)

- No retraining or new model architecture; Isolation Forest + Kitsune stay as the detectors.
- No learned signature model; the rule layer is explicitly a translation layer.
- No new persistent storage; attribution rides on the existing event/incident dicts.

## Risks & mitigations

- **SHAP is heavy / may not fit compute or disk (12GB free).** → It runs on-demand for one
  incident's bounded rows only, and degrades to the free z-score attribution on any failure.
  The tab always renders.
- **Z-score ≠ true model attribution.** → Labeled "baseline-deviation" in the UI; SHAP is the
  faithful headline when available.
- **Rules dismissed as "just if-statements."** → Framed as a translation layer over ML and
  anchored to MITRE ATT&CK technique IDs, which is how real NDR tools present findings.

## Success criteria

- The formerly "Unexplained traffic-flow anomaly" incidents now show a named signature, a
  MITRE technique, non-empty Confirmed evidence, and a confidence that reflects the evidence.
- The Explainability tab renders a per-feature contribution chart for any incident.
- Fallback path verified: with SHAP forced off, the tab still renders via z-score attribution.
- No mock/hardcoded data introduced; everything derives from the real scored flows.
