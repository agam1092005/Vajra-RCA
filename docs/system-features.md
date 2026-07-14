# System Features

The six functional layers the Network Anomaly Root-Cause Assistant implements, and
where each lives in this codebase.

## 1. Ingestion Layer — the input bus
Consumes heterogeneous signals simultaneously and normalizes them into one event schema
(`backend/app/core/events.py :: Event`).

- **Network telemetry & metrics** — packet/flow data, bandwidth, byte/packet counts,
  load, drops. Source: UNSW-NB15 raw flows (`ingestion/unsw.py`).
- **System & application logs** — syslog/OS/server/app logs. Source: HDFS structured
  logs (`ingestion/hdfs.py`) with block-level anomaly ground truth.
- **Security alerts** — signature/label-based alerts. Source: UNSW attack labels →
  `SECURITY_ALERT` events; extensible to Suricata/Snort/firewall logs.
- **Topology data** — infrastructure relationships (`graph/topology.py`), derived from
  real observed communication.
- **Configuration change log** — every change captured with actor, modified entry,
  previous & updated state, and precise timestamp (`ingestion/config_monitor.py`,
  backed by a real git repository).

## 2. Detection & Analytics Layer — the observation window
- **Cross-layer anomaly detection** — Isolation Forest over real flow features
  (`detection/isolation_forest.py`); log/behaviour anomalies from HDFS.
- **Time-window slicing** — a configurable correlation window (default 5 minutes,
  `VAJRA_CORRELATION_WINDOW_S`) around detected anomalies.
- **Signal-noise filtering** — statistical thresholding via the detector's decision
  function (fit on real baselines, not hardcoded cutoffs).

## 3. Topology & Dependency Graph Layer — the structural context
- **Live dependency mapping** — a directed graph (`graph/topology.py`); nodes are
  hosts/services/databases, edges are real observed dependencies. Updates as new flows
  arrive.
- **Upstream/downstream blast-radius evaluation** — `upstream_dependencies`,
  `downstream_dependents`, `blast_radius`, `dependency_path`.

## 4. Correlation & Causal Inference Layer — the RCA engine
`backend/app/rca/`.

- **Cross-layer event aggregator** — merges signals into a synchronized window per node.
- **Causation vs correlation evaluator** — temporal ordering, dependency relationships,
  propagation paths, historical patterns, and corroboration are each scored.
- **Tri-categorized evidence classifier** — every hypothesis carries:
  - **Confirmed** — direct, verifiable proof (e.g. a config commit diff; a matching
    attack signature on the node).
  - **Correlated** — same-window signals not proven causal (e.g. concurrent attack
    traffic under a config-change hypothesis).
  - **Missing** — data that would confirm/reject but is unavailable (e.g. packet-drop
    telemetry for the window).

## 5. Explainable UX & Reporting Layer — the assistant's voice
- **Ranked root-cause hypotheses** — each with a root cause, decomposable confidence
  score, and the three evidence buckets. Uncertain hypotheses are never shown as absolute.
- **Natural-language explanations** — what / where / when / why / supporting / missing
  (`llm/gemini.py`, deterministic fallback when no key).
- **Unified incident timeline** — a synchronized chronological view across all layers.

## 6. Remediation & Audit Layer — the active output
- **Next-step recommendations** — risk-tiered: **diagnostic**, **low-risk**, and
  **high-impact** (the last requires human approval). Generated per hypothesis.
- **Auditable incident trail** — a PostgreSQL ledger (`db/store.py`) recording incidents,
  hypotheses, evidence, recommendations, human actions, and resolution state; supports
  compliance audits, post-incident review and historical comparison.
