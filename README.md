<div align="center">

# Vajra RCA

### Network Anomaly Root-Cause Assistant

**An AI-powered, explainable root-cause analysis platform that ingests real network telemetry, detects anomalies with ensemble ML, maps live infrastructure dependencies, and produces ranked, evidence-backed root-cause hypotheses — separating correlation from causation.**

[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://python.org)
[![Next.js 16](https://img.shields.io/badge/Next.js-16-000000?logo=next.js)](https://nextjs.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi)](https://fastapi.tiangolo.com)
[![Neo4j](https://img.shields.io/badge/Neo4j-5.12-008CC1?logo=neo4j)](https://neo4j.com)
[![Apache Kafka](https://img.shields.io/badge/Kafka-KRaft-231F20?logo=apachekafka)](https://kafka.apache.org)
[![License](https://img.shields.io/badge/License-Proprietary-red)]()

</div>

---

## Table of Contents

- [What is Vajra RCA?](#what-is-vajra-rca)
- [Datasets](#datasets)
- [ML Models & Parameters](#ml-models--parameters)
- [Key Features](#key-features)
- [System Architecture](#system-architecture)
- [Use Cases](#use-cases)
- [Business Impact Analysis](#business-impact-analysis)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [How to Run the Project](#how-to-run-the-project)
- [API Reference](#api-reference)
- [Detection & ML Pipeline](#detection--ml-pipeline)
- [Multi-Agent RCA Pipeline](#multi-agent-rca-pipeline)
- [Configuration Reference](#configuration-reference)
- [Testing](#testing)
- [Roadmap](#roadmap)

---

## What is Vajra RCA?

**Vajra RCA** (Root-Cause Assistant) is an enterprise-grade observability and diagnostics platform purpose-built for network operations centers (NOCs), security operations centers (SOCs), and site reliability engineering (SRE) teams. It goes beyond traditional alerting by answering the critical question: **"Why did this happen?"**

Unlike conventional monitoring tools that simply flag anomalies, Vajra RCA:

1. **Ingests heterogeneous signals** — network flows, system logs, security alerts, topology data, and configuration changes — all normalized into a unified event schema.
2. **Detects anomalies with ensemble ML** — Isolation Forest (batch, unsupervised), Kitsune (online, autoencoder-based), and Vajra ML models (pre-trained classifiers) run in parallel.
3. **Maps live dependencies** — a Neo4j-backed directed graph of infrastructure relationships, built from real observed communication patterns.
4. **Infers root cause with causal reasoning** — a LangGraph 8-agent pipeline performs multi-layer correlation, temporal scoring, dependency-path analysis, and historical pattern matching.
5. **Explains transparently** — every hypothesis carries a decomposable confidence score, tri-categorized evidence (Confirmed / Correlated / Missing), risk-tiered remediation steps, and blast-radius impact analysis.

> **Built on real datasets** (UNSW-NB15, NSL-KDD, HDFS logs) and **real configuration changes** (a live git repository). No mock data, no hardcoded verdicts — every signal is genuine and every hypothesis is derived at runtime.

---

## Datasets

Vajra RCA is powered by **three real, publicly available cybersecurity and systems datasets**. No synthetic or fabricated data is used at any point — all detection, correlation, and scoring operates on genuine records.

### 1. UNSW-NB15 (Network Flow Telemetry & Security Alerts)

> **Source**: Australian Centre for Cyber Security (ACCS), University of New South Wales  
> **Paper**: Moustafa & Slay, "UNSW-NB15: A Comprehensive Data Set for Network Intrusion Detection" (MilCIS 2015)  
> **Size**: ~2.5M records across 4 raw CSV files (~2.2 GB)  
> **Module**: `ingestion/unsw.py`, `ingestion/schema.py`  

**What it is**: A modern network intrusion dataset created using the IXIA PerfectStorm tool in a realistic network environment. It contains real network flows (not packet captures) with full IP addressing, making it uniquely suitable for topology inference.

**What's in it — 49 columns per flow record**:

| Column Group | Columns | Description |
|---|---|---|
| **Source/Destination** | `srcip`, `sport`, `dstip`, `dsport` | Real IPv4 addresses and port numbers (some hex-encoded) |
| **Protocol** | `proto`, `state`, `service` | Transport protocol (TCP/UDP/ICMP), connection state, and application service |
| **Timing** | `Stime`, `Ltime`, `dur` | Unix epoch start/last timestamps and flow duration (seconds) |
| **Volume** | `sbytes`, `dbytes`, `Spkts`, `Dpkts` | Source/destination bytes and packet counts |
| **Load** | `Sload`, `Dload`, `smeansz`, `dmeansz` | Bits/sec load and mean packet sizes |
| **Network Quality** | `sloss`, `dloss`, `tcprtt`, `synack`, `ackdat` | Packet loss counts, TCP round-trip time, SYN→ACK and ACK→DATA timing |
| **TTL** | `sttl`, `dttl` | Source and destination time-to-live values |
| **Jitter** | `Sjit`, `Djit` | Source and destination inter-packet jitter |
| **Windows** | `swin`, `dwin` | TCP window sizes (used for buffer analysis) |
| **TCP State** | `stcpb`, `dtcpb` | TCP base sequence numbers |
| **Connection Counts** | `ct_srv_src`, `ct_srv_dst`, `ct_dst_ltm`, `ct_src_ltm`, `ct_src_dport_ltm`, `ct_dst_sport_ltm`, `ct_dst_src_ltm` | Connection-tracking features (service fan-out, destination fan-out, etc.) |
| **Content** | `trans_depth`, `res_bdy_len`, `ct_flw_http_mthd`, `is_ftp_login`, `ct_ftp_cmd` | HTTP transaction depth, response body length, FTP login indicators |
| **Binary Flags** | `is_sm_ips_ports`, `ct_state_ttl` | Same IP/port indicator, TTL-state combinations |
| **Labels** | `attack_cat`, `Label` | Attack category name and binary label (0=normal, 1=attack) |

**Attack Categories** (9 real categories with severity mapping):

| Attack Category | Mapped Severity | Description |
|---|---|---|
| Generic | `MEDIUM` | Generic attacks |
| Exploits | `HIGH` | Known vulnerability exploits |
| Fuzzers | `LOW` | Protocol/application fuzzing |
| DoS | `HIGH` | Denial-of-Service floods |
| Reconnaissance | `MEDIUM` | Network scanning and probing |
| Analysis | `MEDIUM` | Traffic analysis attacks |
| Backdoor / Backdoors | `CRITICAL` | Backdoor installation/access |
| Shellcode | `CRITICAL` | Shellcode injection |
| Worms | `CRITICAL` | Self-propagating worms |

**How Vajra uses it**:
- **Network flow telemetry** → `NETWORK_FLOW` events with full IP/port/timing/volume attributes
- **Security alerts** → `SECURITY_ALERT` events for every flow labelled as an attack (`Label=1`)
- **Topology inference** → Real `srcip → dstip` communication builds the Neo4j dependency graph
- **Anomaly detection** → 20 numeric features fed to Isolation Forest for unsupervised detection
- **Kitsune input** → Flow attributes converted to packets for online autoencoder detection
- **Business impact** → `sloss`, `dloss`, `tcprtt`, `sjit`, `djit`, `swin`, `dwin` drive protocol impact metrics

---

### 2. NSL-KDD (Labelled Intrusion Detection Benchmark)

> **Source**: University of New Brunswick (UNB)  
> **Original**: KDD Cup 1999, refined by Tavallaee et al. to remove duplicates  
> **Size**: 125,973 training records + 22,544 test records  
> **Module**: `ingestion/nsl_kdd.py`, `ingestion/schema.py`  

**What it is**: The cleaned, non-redundant successor to the KDD'99 dataset — the most widely used benchmark for network intrusion detection research. Contains per-connection records (no IPs or timestamps) with 41 features and labelled attack types.

**What's in it — 43 columns per record** (41 features + label + difficulty):

| Column Group | Columns | Description |
|---|---|---|
| **Basic** | `duration`, `protocol_type`, `service`, `flag` | Connection duration, transport protocol, application service (http, smtp, ftp, etc.), TCP connection status |
| **Content** | `src_bytes`, `dst_bytes`, `land`, `wrong_fragment`, `urgent` | Byte counts, land attack flag, fragmentation errors, urgent packets |
| **Intrusion Indicators** | `hot`, `num_failed_logins`, `logged_in`, `num_compromised`, `root_shell`, `su_attempted`, `num_root` | Hot indicators, failed logins, root access attempts |
| **File Access** | `num_file_creations`, `num_shells`, `num_access_files`, `num_outbound_cmds` | File operations, shell access, outbound command count |
| **Host Login** | `is_host_login`, `is_guest_login` | Login type indicators |
| **Traffic Stats (2s)** | `count`, `srv_count`, `serror_rate`, `srv_serror_rate`, `rerror_rate`, `srv_rerror_rate`, `same_srv_rate`, `diff_srv_rate`, `srv_diff_host_rate` | 2-second window traffic statistics |
| **Host Stats (100)** | `dst_host_count`, `dst_host_srv_count`, `dst_host_same_srv_rate`, `dst_host_diff_srv_rate`, `dst_host_same_src_port_rate`, `dst_host_srv_diff_host_rate`, `dst_host_serror_rate`, `dst_host_srv_serror_rate`, `dst_host_rerror_rate`, `dst_host_srv_rerror_rate` | 100-connection window host statistics |
| **Labels** | `label`, `difficulty` | Attack name (e.g., `neptune`, `smurf`, `normal`) and classification difficulty score |

**Attack Families** (4 families, 39 attack types):

| Family | Attack Types | Description |
|---|---|---|
| **DoS** (Denial of Service) | `neptune`, `back`, `land`, `pod`, `smurf`, `teardrop`, `mailbomb`, `apache2`, `processtable`, `udpstorm`, `worm` | Overwhelm resources to deny service |
| **Probe** (Surveillance) | `ipsweep`, `nmap`, `portsweep`, `satan`, `mscan`, `saint` | Network scanning and reconnaissance |
| **R2L** (Remote to Local) | `ftp_write`, `guess_passwd`, `imap`, `multihop`, `phf`, `spy`, `warezclient`, `warezmaster`, `sendmail`, `named`, `snmpgetattack`, `snmpguess`, `xlock`, `xsnoop`, `httptunnel` | Unauthorized remote access |
| **U2R** (User to Root) | `buffer_overflow`, `loadmodule`, `perl`, `rootkit`, `ps`, `sqlattack`, `xterm` | Privilege escalation |

**How Vajra uses it**:
- **Detector training/validation** → Isolation Forest is trained on benign rows and validated against labelled attack rows
- **Cross-dataset validation** → `scripts/dataset_validation.py` produces precision/recall/F1/ROC-AUC on the test split
- **38 numeric features** used for validation (no categorical encoding)

---

### 3. HDFS (Hadoop Distributed File System Logs)

> **Source**: Xu et al., "Detecting Large-Scale System Problems by Mining Console Logs" (SOSP 2009)  
> **Size**: HDFS_2k structured sample (2,000 pre-parsed log entries) + anomaly_label.csv (ground truth per block ID)  
> **Module**: `ingestion/hdfs.py`  

**What it is**: Real system logs from a Hadoop cluster, structured using log parsing (Drain). Contains Date, Time, Level, Component, Content, and parsed EventId/EventTemplate fields. The companion `anomaly_label.csv` provides block-level anomaly ground truth (`Normal` / `Anomaly`).

**What's in it — per log entry**:

| Column | Description | Example |
|---|---|---|
| `Date` | Date in `yymmdd` format | `081109` |
| `Time` | Time in `HHMMSS` format | `203615` |
| `Pid` | Process ID | `26046` |
| `Level` | Log level | `INFO`, `WARN`, `ERROR`, `FATAL` |
| `Component` | HDFS component | `dfs.DataNode$`, `dfs.FSNamesystem` |
| `Content` | Raw log message | `Received block blk_-1608999687919862906 src: /...` |
| `EventId` | Parsed event template ID | `E5`, `E11` |
| `EventTemplate` | Parsed event template | `Receiving block <*> src: <*> dest: <*>` |

**Anomaly Label File** (`anomaly_label.csv`):

| Column | Description |
|---|---|
| `BlockId` | HDFS block identifier (e.g., `blk_-1608999687919862906`) |
| `Label` | `Normal` or `Anomaly` — ground truth for the block's lifecycle |

**Error Detection Logic**: Logs are classified as errors based on:
- Log level: `ERROR`, `WARN`, or `FATAL`
- Content keywords: `exception`, `error`, `fail`, `interrupted`, `corrupt`, `not served`

**How Vajra uses it**:
- **System logs** → `LOG` events for normal entries, `SECURITY_ALERT` for anomaly-labelled blocks
- **Cross-layer correlation** → Log anomalies are correlated with concurrent network flow anomalies in the same time window
- **Timeline enrichment** → Log entries enrich the incident timeline with system-layer context
- **GraphRAG** → SOP-108 (HDFS Log Error Escalation) is surfaced when HDFS errors are detected

---

## ML Models & Parameters

Vajra RCA employs three independent ML detection engines plus a post-hoc signature classifier. Each is configured with specific hyperparameters tuned for the production deployment.

### Model 1: Isolation Forest (Batch, Unsupervised)

> **Module**: `detection/isolation_forest.py`  
> **Library**: scikit-learn `sklearn.ensemble.IsolationForest`  
> **Purpose**: Primary anomaly detector — identifies statistically anomalous network flows without relying on attack labels  

**Hyperparameters**:

| Parameter | Value | Description |
|---|---|---|
| `n_estimators` | `200` | Number of isolation trees in the ensemble |
| `contamination` | `0.1` (configurable via `VAJRA_IFOREST_CONTAMINATION`) | Expected proportion of anomalies in the training data |
| `random_state` | `42` | Fixed seed for reproducibility |
| `n_jobs` | `-1` | Use all available CPU cores for parallel tree building |
| `max_train_rows` | `40000` (configurable via `VAJRA_IFOREST_MAX_TRAIN_ROWS`) | Cap on training rows for fast fits (~2s) |

**Preprocessing**: `StandardScaler` (zero mean, unit variance normalization) applied before fitting

**Input Features** (20 numeric UNSW-NB15 flow features):

| # | Feature | Description |
|---|---|---|
| 1 | `dur` | Flow duration (seconds) |
| 2 | `sbytes` | Source → destination bytes |
| 3 | `dbytes` | Destination → source bytes |
| 4 | `sttl` | Source time-to-live |
| 5 | `dttl` | Destination time-to-live |
| 6 | `sloss` | Source packet loss count |
| 7 | `dloss` | Destination packet loss count |
| 8 | `Sload` | Source bits per second |
| 9 | `Dload` | Destination bits per second |
| 10 | `Spkts` | Source packet count |
| 11 | `Dpkts` | Destination packet count |
| 12 | `smeansz` | Source mean packet size |
| 13 | `dmeansz` | Destination mean packet size |
| 14 | `tcprtt` | TCP round-trip time |
| 15 | `synack` | SYN → ACK time |
| 16 | `ackdat` | ACK → DATA time |
| 17 | `ct_srv_src` | Connections to same service from same source |
| 18 | `ct_srv_dst` | Connections to same service from same destination |
| 19 | `ct_dst_ltm` | Connections to same destination in last 100 |
| 20 | `ct_src_ltm` | Connections from same source in last 100 |

**Output**:
- `anomaly_score` = negated `decision_function` (higher = more anomalous)
- `is_anomaly` = binary prediction (`predict()` returns -1 for anomaly, +1 for normal)
- `attribution` = top-5 deviating features with z-scores vs the fitted normal baseline

**Severity Mapping**:
| Anomaly Score | Severity |
|---|---|
| > 0.15 | `HIGH` |
| > 0.05 | `MEDIUM` |
| ≤ 0.05 | `LOW` |

**Confidence**: `min(1.0, 0.5 + anomaly_score)` — bounded to [0.5, 1.0]

---

### Model 2: Kitsune KitNET (Online, Autoencoder Ensemble)

> **Module**: `detection/kitsune.py`  
> **Paper**: Mirsky et al., "Kitsune: An Ensemble of Autoencoders for Online Network Intrusion Detection" (NDSS 2018)  
> **Purpose**: Online, streaming anomaly detector that learns per-host traffic patterns incrementally  

**Architecture**:

```
 Raw Flow → AfterImage (incremental feature extraction)
                │
                ▼
    9-dimensional feature vector
                │
    ┌───────────┼───────────┐
    ▼           ▼           ▼
  AE₁         AE₂  ...   AE₁₀     ← 10 sub-autoencoders (random feature partitions)
    │           │           │
    ▼           ▼           ▼
  score₁     score₂     score₁₀
    │           │           │
    └───────────┼───────────┘
                ▼
         Output AE (merges 10 sub-scores)
                │
                ▼
     Final reconstruction error
```

**Hyperparameters**:

| Parameter | Value | Description |
|---|---|---|
| `ensemble_size` | `10` | Number of sub-autoencoders in the ensemble |
| `grace_period` | `1000` | Packets processed in training mode before switching to detection |
| `anomaly_threshold` | `0.1` | Reconstruction error above this → anomalous |
| `learning_rate` | `0.1` | Backpropagation learning rate for all autoencoders |
| `max_host_limit` | `255` | Maximum tracked hosts in AfterImage (LRU eviction after) |

**Sub-Autoencoder Architecture** (per AE unit):

| Layer | Specification |
|---|---|
| Input | `input_size` features (varies per partition) |
| Hidden | `max(input_size // 2, 1)` neurons |
| Activation | `tanh` (both hidden and output layers) |
| Weights Init | `np.random.randn * 0.1` |
| Loss | Mean Squared Error (reconstruction error) |
| Training | Online backpropagation (one sample at a time) |
| Threshold | `mean_error + 3 × std_error` (3σ rule, per-AE) |

**AfterImage Feature Extraction** (9 features per flow):

| # | Feature | Computation |
|---|---|---|
| 1 | Host connection count | Cumulative per-source-IP |
| 2 | Total bytes | Cumulative per-source-IP |
| 3 | Average bytes per connection | total_bytes / count |
| 4 | Inter-arrival delta | Current timestamp − last timestamp |
| 5 | Arrival rate | 1 / max(delta, 0.001) |
| 6 | Protocol diversity | Count of unique protocols per host |
| 7 | Port diversity | Count of unique destination ports per host |
| 8 | Current packet length | Raw packet size |
| 9 | Destination port | Raw port number |

**Thread Safety**: Global singleton (`get_kitsune_engine()`) with `threading.Lock` around `process_packet()`

---

### Model 3: Vajra ML Bridge (Pre-trained Classifiers)

> **Module**: `ingestion/vajra_bridge.py`  
> **Source Models**: `ml_models/` (`.pkl` and `.joblib` serialized)  
> **Loader**: `MLModelManager`  
> **Purpose**: Supervised threat classifiers trained on labelled datasets — complement the unsupervised detectors  

**Loaded Models**:

| Model Name | Format | Threat Types Detected |
|---|---|---|
| Network Anomaly Detector | `.pkl` / `.joblib` | `network_anomaly` |
| DDoS Attack Classifier | `.pkl` / `.joblib` | `ddos_attack` |
| Insider Threat Detector | `.pkl` / `.joblib` | `insider_threat`, `suspicious_access_time`, `suspicious_device_usage` |
| Data Exfiltration Classifier | `.pkl` / `.joblib` | `data_exfiltration_email`, `data_exfiltration_http` |

**Excluded Models** (skipped at load time):

| Model | Reason |
|---|---|
| `domain_classifier.h5` | Requires TensorFlow (incompatible with Python 3.12 venv) |
| `gnn_fingerprint.tflite` | Requires TensorFlow Lite runtime |

**Severity Mapping** (per threat type):

| Threat Type | Severity |
|---|---|
| `none` | `INFO` |
| `network_anomaly` | `MEDIUM` |
| `ddos_attack` | `HIGH` |
| `insider_threat` | `HIGH` |
| `suspicious_access_time` | `MEDIUM` |
| `suspicious_device_usage` | `MEDIUM` |
| `data_exfiltration_email` | `HIGH` |
| `data_exfiltration_http` | `HIGH` |
| `ml_detected_threat` (fallback) | `MEDIUM` |

**Integration**: Each `is_threat=True` prediction becomes a `SECURITY_ALERT` event with the model's confidence score, threat type, prediction probabilities, and inference time.

---

### Model 4: Behavioral Signature Classifier (Post-hoc, Rule-based)

> **Module**: `detection/signatures.py`  
> **Purpose**: Translates Isolation Forest feature attributions into named behavioral signatures anchored in MITRE ATT&CK  
> **Note**: This is **not** a detector — the ML detects; this interprets its output into analyst-readable language  

**Classification Rules** (evaluated in priority order):

| Priority | Signature | MITRE ID | Detection Rule (z-score conditions) | Interpretation |
|---|---|---|---|---|
| 1 | **DoS / Flood** | T1498 | `z(Spkts) > 2 OR z(Sload) > 2` AND `z(dur) < -0.5` | High packet/load volume in very short-lived flows |
| 2 | **Reflection / Amplification** | T1498.002 | `z(dbytes) > 2` AND `z(sbytes) ≤ 0.5` | Response payload far exceeds request payload |
| 3 | **Data Exfiltration** | T1041 | `z(sbytes) > 2 OR z(smeansz) > 2 OR z(Sload) > 2` AND `z(dur) > 0.5` | Sustained large outbound transfer over extended flow |
| 4 | **Port / Host Scan** | T1046 | `z(ct_dst_ltm) > 1.5 OR z(ct_srv_dst) > 1.5` AND `z(sbytes) ≤ 0.5` | Many short connections with minimal payload across destinations |
| 5 | **Beaconing / C2** | T1071 | `z(ct_srv_dst) > 1.5` AND `abs(z(sbytes)) < 1.0` | Repeated same-service contact consistent with C2 beaconing |
| 6 | **Anomalous Volumetric** | — | Fallback (no rule matches) | Abnormal deviation in top-3 attributed features |

**Input**: `attribution` list from Isolation Forest (top-5 features with z-scores)  
**Output**: `{label, mitre_id, mitre_name, matched_features, sentence}` — surfaced in the UI and incident report

---

### Model Attribution & Explainability

**SHAP TreeExplainer** (when `shap` package is available):
- Applied to the Isolation Forest model for model-faithful feature importance
- Returns per-feature contribution values for a node's anomalous flows
- Accessed via `GET /api/incidents/{id}/attribution`

**Baseline-Deviation Fallback** (always available):
- Uses the StandardScaler's learned mean/scale to compute z-scores
- Top-k features ranked by `|z-score|`, filtered to `|z| ≥ 1.0`
- Free, instant, and honest: "which features deviate most from the learned-normal baseline"

---

## Key Features

### 1. Multi-Source Signal Ingestion Layer

The ingestion layer consumes five heterogeneous signal types simultaneously and normalizes them into a unified `Event` schema via the Apache Kafka event bus (with graceful in-memory fallback):

| Signal Type | Source | Module | Description |
|---|---|---|---|
| **Network Flows** | UNSW-NB15 raw CSVs | `ingestion/unsw.py` | Real packet/flow data with src/dst IPs, ports, protocols, byte counts, timestamps, and 49 features per flow |
| **System Logs** | HDFS structured logs | `ingestion/hdfs.py` | Parsed syslog records (Date/Time/Level/Component/Content) with block-level anomaly ground truth labels |
| **Security Alerts** | UNSW-NB15 attack labels + Vajra ML | `ingestion/unsw.py`, `ingestion/vajra_bridge.py` | Real labelled attacks (Generic, Exploits, DoS, Backdoor, Shellcode, Worms, etc.) mapped to severity levels |
| **Configuration Changes** | Real git repository | `ingestion/config_monitor.py` | Every change is a real commit with actor, timestamp, diff, and governance mapping — not simulated |
| **ML Model Predictions** | Pre-trained models | `ingestion/vajra_bridge.py` | Pre-trained sklearn/joblib models for network anomaly, DDoS, insider threat, and data exfiltration detection |

**Unified Event Schema** (`core/events.py`): Every signal is normalized into a single `Event` dataclass with fields for event type, source, node, timestamp, severity, confidence, signature, description, and source-specific attributes — enabling true cross-layer correlation.

---

### 2. Ensemble Anomaly Detection Engine

Three detection engines run simultaneously, each providing independent anomalous signal:

#### Isolation Forest (Batch, Unsupervised)
- **Module**: `detection/isolation_forest.py`
- **Algorithm**: scikit-learn `IsolationForest` with 200 estimators, fit on real observed traffic baselines
- **Features**: 20 numeric UNSW-NB15 flow features (duration, bytes, packets, load, TTL, loss, jitter, RTT, etc.)
- **Output**: Per-flow anomaly score + per-feature z-score attribution (top deviating features from learned-normal baseline)
- **Validation**: `validate()` method computes precision/recall/F1 against real dataset labels (labels are never used for detection, only measurement)

#### Kitsune (Online, Autoencoder Ensemble)
- **Module**: `detection/kitsune.py`
- **Algorithm**: KitNET — an ensemble of autoencoders (Mirsky et al., NDSS 2018) for online network intrusion detection
- **Architecture**: AfterImage incremental feature extractor → random feature partition → ensemble of single-layer autoencoders → output-layer autoencoder
- **Key Properties**: Thread-safe singleton, 1000-packet grace period for training, processes one flow at a time, anomaly score = reconstruction error above 3σ threshold
- **Output**: `KitsuneResult` with anomaly score, reconstruction error, and source/destination IPs

#### Vajra ML Bridge (Pre-trained Classifiers)
- **Module**: `ingestion/vajra_bridge.py`
- **Models**: Loads pre-trained `.pkl`/`.joblib` models via the integrated `MLModelManager`
- **Threat Types**: Network anomaly, DDoS attack, insider threat, suspicious access timing, data exfiltration (email/HTTP), suspicious device usage
- **Integration**: Each model's threat prediction is converted into a `SECURITY_ALERT` event with confidence score

---

### 3. Behavioral Signature Classifier (MITRE ATT&CK Mapped)

**Module**: `detection/signatures.py`

Translates Isolation Forest feature attributions into named behavioral signatures anchored in the MITRE ATT&CK framework:

| Behavioral Pattern | MITRE ID | Detection Logic |
|---|---|---|
| DoS / Flood | T1498 | High packet/load volume (Spkts, Sload > 2σ) in very short-lived flows (dur < -0.5σ) |
| Reflection / Amplification | T1498.002 | Response payload (dbytes > 2σ) far exceeds request payload |
| Data Exfiltration | T1041 | Sustained large outbound transfer (sbytes, smeansz > 2σ) over extended flows |
| Port / Host Scan | T1046 | High destination fan-out (ct_dst_ltm, ct_srv_dst > 1.5σ) with minimal payload |
| Beaconing / C2 | T1071 | Repeated same-service contact with small payloads |

---

### 4. Neo4j Dependency Topology Graph

**Module**: `graph/topology.py`

A live, Neo4j-backed directed graph where edge `src → dst` means "src was observed communicating to dst" (client → server dependency):

- **`build_from_unsw(df)`** — Constructs the full graph from real UNSW-NB15 flows with batch Cypher upserts (2000 edges/batch)
- **`upstream_dependencies(node)`** — Servers that `node` calls (what it relies on)
- **`downstream_dependents(node)`** — Clients calling `node` (who relies on it)
- **`blast_radius(node, max_depth=4)`** — All nodes transitively depending on `node` (transitive predecessors), returned with levels by hop distance
- **`dependency_path(source, target)`** — Shortest dependency chain between two nodes
- **`to_cytoscape(top_n=60)`** — Serialized sub-graph for dashboard visualization
- **Node Roles**: Automatically inferred from port/service data (web, dns, database, cache, router, ftp, ssh, etc.)

---

### 5. Correlation & Causal Inference Engine (The RCA Core)

**Module**: `rca/engine.py`, `rca/scoring.py`

The intellectual core of Vajra RCA. Turns a window of correlated real events around an affected node into ranked, evidence-backed root-cause hypotheses. **Causation vs correlation** is decided from temporal ordering, the real dependency graph, config-change timing, and independent corroboration.

#### Hypothesis Types Generated

| Hypothesis Kind | Trigger | Key Evidence |
|---|---|---|
| **Configuration Change** | A config commit on/upstream of the affected node precedes the anomaly | Real git diff, dependency path, temporal proximity (5s causal window) |
| **External Attack** | Security alert signatures targeting the node | Attack category, source IP attribution, multi-vector patterns |
| **Upstream Dependency Failure** | Anomaly on an upstream node precedes the downstream anomaly | Dependency path, temporal ordering, propagation pattern |
| **Behavioral Anomaly** | Unsupervised detector flags + MITRE signature match | Feature attribution (z-scores), behavioral signature, volumetric pattern |

#### Decomposable Causal Scoring (`rca/scoring.py`)

Each hypothesis accrues named, additive components capped at 100:

| Score Component | Weight | Meaning |
|---|---|---|
| `config_change_within_5s` | +30 | Config change on/upstream of node just before the anomaly |
| `direct_upstream_dependency` | +30 | A real dependency path supports propagation |
| `confirmed_match` | +30 | Confirmed direct evidence (diff/signature/label match) |
| `explained_signature` | +30 | Named MITRE-mapped behavioral signature |
| `matching_propagation_path` | +20 | Upstream anomaly temporally precedes downstream |
| `feature_attribution` | +15 | Specific deviating features named from the detector |
| `historical_pattern_match` | +10 | A similar past incident exists (RAG/history) |
| `independent_corroboration` | +10 | An independent supporting signal |

The score is shown in the UI so operators can see exactly **why** a hypothesis ranks where it does — **correlation is never silently promoted to causation**.

#### Tri-Categorized Evidence Classifier

Every hypothesis carries three evidence buckets:

- **Confirmed** — Direct, verifiable proof (e.g., a config commit diff, a matching attack signature, a dependency path)
- **Correlated** — Same-window signals not proven causal (e.g., concurrent attack traffic under a config-change hypothesis)
- **Missing** — Data that would confirm/reject the hypothesis but is unavailable (e.g., packet-drop telemetry for the window)

#### Risk-Tiered Remediation Recommendations

Each hypothesis generates remediation steps classified into three tiers:

| Tier | Example | Requires Approval |
|---|---|---|
| **Diagnostic** | "Collect packet-drop metrics on X for 5 minutes" | No |
| **Low-Risk** | "Rate-limit traffic from source IP to target node" | No |
| **High-Impact** | "Roll back commit abc123 on routing.yaml" | **Yes** |

High-impact recommendations include **blast-radius warnings** computed from the topology graph (e.g., "This action will temporarily sever connections for downstream dependent services (A, B, C and 5 others)").

---

### 6. LangGraph Multi-Agent Diagnostic Pipeline

**Module**: `agents/graph.py`, `agents/nodes.py`, `agents/state.py`

An 8-node LangGraph state graph orchestrates the full diagnostic workflow:

```
START → Coordinator → Metric → Log → Trace → Graph → RAG → Root Cause → Report → END
```

| Agent | Responsibility |
|---|---|
| **Coordinator** | Bounds the raw event window to 300 events, sets up the shared state |
| **Metric Agent** | Scans telemetry metrics — flow count, anomaly count, average anomaly score, max severity |
| **Log Agent** | Examines HDFS error/warning logs within the event window |
| **Trace Agent** | Extracts high-volume transfer flows as proxy for distributed trace spans |
| **Graph Agent** | Walks the Neo4j topology — upstream dependencies, downstream dependents, blast radius |
| **RAG Agent** | GraphRAG search (Qdrant vector similarity + Neo4j topology enrichment) for matching SOPs/runbooks |
| **Root Cause Agent** | Runs the causal inference `RCAEngine.build_incident()` + awards historical pattern match bonuses from GraphRAG |
| **Report Agent** | Synthesizes the final incident report with timeline, business impact, blast radius, and deterministic explanation |

**Live Streaming**: The pipeline streams `agent_step` events to the frontend via Socket.IO, so the dashboard shows real-time progress as each agent completes.

---

### 7. GraphRAG — Topology-Aware Retrieval-Augmented Generation

**Modules**: `rag/graphrag.py`, `rag/qdrant.py`

A combined Qdrant vector search + Neo4j topology traversal system:

1. **Qdrant Vector Search**: 8 pre-seeded SOPs (Redis recovery, routing misconfiguration, DDoS mitigation, DB connection pool, anomaly spike, backdoor/shellcode, config rollback, HDFS log escalation) indexed with stable TF-IDF-style hash embeddings (768-dim, deterministic, no live LLM call)
2. **Neo4j Topology Enrichment**: Each match is enriched with the focal node's upstream dependencies, downstream dependents, and blast radius count
3. **Keyword Fallback**: If Qdrant is unreachable, a keyword overlap scorer ensures SOPs are always returned

**Design Decision**: Embeddings use a deterministic `hashlib`-based function (not Python's randomized `hash()`) — never a live LLM call. Retrieval runs synchronously on the incident hot path, so it must be instant and deterministic.

---

### 8. Natural-Language Explanation & Chat (Gemini)

**Module**: `llm/gemini.py`

- **Deterministic Explanation** (`deterministic_explanation()`): Always available, generates structured what/where/when/why/supporting/missing/narrative fields from the scored incident data — used inline on the incident-creation path
- **Gemini Narrative** (`explain_incident()`): On-demand via `POST /api/incidents/{id}/explain`, generates a richer operator-readable narrative using Gemini 2.5 Pro with structured JSON output. Falls back gracefully to deterministic if no API key or network error
- **Grounded Chat** (`chat()`): Conversational Q&A about a specific incident, grounded only in that incident's data (no hallucination). Available via `POST /api/incidents/{id}/chat`

**Key Design**: Gemini **never performs detection or causation** — that is decided deterministically upstream. It only synthesizes the already-correlated structured incident into natural language.

---

### 9. Real-Time Business Impact Analysis

**Module**: `pipeline.py`, `rca/engine.py`

Vajra RCA algorithmically computes real-time business impact metrics based on the sliding window event state:

#### Live Dashboard Metrics (Streaming)
- **UPI/Card Payment Success Rate**: Nominal 99.4%, dynamically degraded based on threat coefficient (anomalies × 2.0 + alerts × 3.5 + critical alerts × 5.0)
- **API Checkout Latency**: Baseline 85ms, scaled by threat index (up to 1685ms+ under max threat)
- **Estimated Revenue Loss/Min**: Proportional to success rate drop and transaction volume
- **Protocol Impact Panel**: Real-time TCP packet loss %, UDP packet loss %, TCP buffer delay (RTT), UDP jitter, TCP window size, buffer overflow risk classification (nominal/degraded/critical)

#### Per-Incident Impact Assessment
- **Cause-Specific Scaling**: Config changes get 2.0× multiplier, attacks get 1.5×, upstream failures get 1.2×
- **Blast-Radius Severity Factor**: `min(1.0, max(0.2, (blast_count × 0.15) + 0.2))` — incidents affecting more downstream nodes are scored higher
- **Affected Business Flow**: Automatically identified (Checkout → Payment Gateway, External API Ingestion, Internal Transaction Processing)
- **Dynamic Description**: Human-readable narrative explaining the business impact chain

---

### 10. PDF Report Generation & Object Storage

**Module**: `utils/reporter.py`

- Compiles incident metadata, ranked hypotheses, evidence classification, recommendations (with blast-radius warnings), and chronological timeline into a professionally styled PDF using ReportLab
- Automatically uploads to MinIO object storage (`vajra-reports` bucket with public read policy)
- Returns a direct download URL; gracefully degrades if MinIO is unreachable

---

### 11. PostgreSQL Audit Ledger

**Module**: `db/store.py`

A non-repudiable, queryable incident history:

- **Incident CRUD**: Save, list, get, update fields (upsert on conflict)
- **Status Lifecycle**: open → investigating → mitigated → resolved (with actor tracking)
- **Audit Trail**: Every action logged with timestamp, incident ID, actor, action type, and detail
- **Statistics**: Total incidents, open incidents count

---

### 12. Apache Kafka Event Bus

**Module**: `core/events.py`

- **Topics**: `vajra_metrics`, `vajra_logs`, `vajra_alerts`, `vajra_anomalies`, `vajra_config_changes`
- **Producer/Consumer**: `aiokafka`-based async producer and consumer with automatic topic routing
- **Graceful Degradation**: If Kafka is unreachable at startup, seamlessly falls back to in-memory pub/sub with zero code changes
- **Event Streaming**: Supports async iterator-based streaming (`bus.stream()`) for downstream consumers

---

### 13. Live Replay Engine

**Module**: `pipeline.py`

Historical dataset records are streamed on the wall clock so that real-time actions (like config changes) align temporally with the streamed anomalies:

- **UNSW Flow Replay**: 30 events/sec with Isolation Forest scoring, Kitsune online detection, and Vajra ML predictions per flow
- **HDFS Log Replay**: 5 events/sec alongside the UNSW stream
- **Config Change Injection**: Real git commits that genuinely precede the streamed anomalies — enabling true causal correlation
- **Controllable**: Start/stop via API (`POST /api/telemetry/replay/toggle`) or dashboard toggle

---

### 14. Real-Time Dashboard (Next.js)

**Frontend**: `frontend/src/`

A dark-themed, real-time operations dashboard built with Next.js 16, React 19, and TailwindCSS 4:

| Component | File | Purpose |
|---|---|---|
| **Dashboard Page** | `app/page.tsx` | Main layout: stat tiles, signal rate chart, topology graph, incident list, incident detail panel, login gate |
| **Incident Detail** | `components/IncidentDetail.tsx` | Full incident view: hypotheses with score breakdowns, evidence tabs, timeline, business impact, SHAP attribution, recommendations, chat, report generation |
| **Topology Graph** | `components/TopologyGraph.tsx` | Interactive Neo4j dependency visualization using React Flow (@xyflow/react) with focal/impacted node highlighting |
| **Metrics Chart** | `components/MetricsChart.tsx` | Live signal rate chart (flows/anomalies/alerts per second) using Recharts |
| **Agent Pipeline** | `components/AgentPipeline.tsx` | Live 8-step progress stepper showing which LangGraph agent is currently executing |
| **Socket.IO Client** | `lib/socket.ts` | Real-time event streaming (metrics, incidents, alerts, anomalies, agent steps) |

**Live Features**: Socket.IO-powered real-time updates, per-agent-step progress animation, config change injection, telemetry replay toggle, Grafana iframe embedding, operator authentication.

---

## System Architecture

```mermaid
graph TD
    subgraph DataSources["Data Sources"]
        UNSW["UNSW-NB15 Flows"]
        NSL["NSL-KDD Records"]
        HDFS["HDFS System Logs"]
        Config["Config Changes (Git)"]
    end

    subgraph Ingestion["Ingestion Layer"]
        Adapters["Ingestion Adapters<br/>(unsw.py, hdfs.py, config_monitor.py, vajra_bridge.py)"]
        EventBus["Kafka Event Bus / In-Memory Pub-Sub<br/>(core/events.py)"]
    end

    subgraph Detection["Ensemble Detection Layer"]
        IForest["Isolation Forest Anomaly Detector"]
        Kitsune["Kitsune Online Autoencoder Ensemble"]
        MLBridge["ML Bridge Pre-trained Classifiers"]
        Sigs["Behavioral Signature Classifier"]
    end

    subgraph Correlation["Correlation, Topology & GraphRAG"]
        Neo4j["Neo4j Dependency Graph"]
        GraphRAG["Qdrant GraphRAG (SOPs)"]
        SlidingWindow["5-Min Sliding Window & Causal Scorer"]
    end

    subgraph Pipeline["LangGraph 8-Agent Diagnostic Workflow"]
        Agents["Coordinator ➔ Metric ➔ Log ➔ Trace ➔ Graph ➔ RAG ➔ RootCause ➔ Report"]
    end

    subgraph Outputs["Persistence, API & Presentation"]
        Postgres[(PostgreSQL Incident Ledger)]
        FastAPI["FastAPI + Socket.IO Server"]
        MinIO[(MinIO PDF Report Archive)]
        Dashboard["Next.js Operations Dashboard"]
    end

    UNSW & NSL & HDFS & Config --> Adapters
    Adapters --> EventBus
    EventBus --> IForest & Kitsune & MLBridge
    IForest --> Sigs
    
    IForest & Kitsune & MLBridge & Sigs --> SlidingWindow
    Neo4j <--> SlidingWindow
    GraphRAG <--> SlidingWindow

    SlidingWindow --> Agents
    
    Agents --> Postgres
    Agents --> FastAPI
    Agents --> MinIO
    FastAPI --> Dashboard
```

### Data Flow

```mermaid
flowchart TD
    subgraph RawData["Raw Telemetry & Changes"]
        UNSW["UNSW-NB15 Flows"]
        NSL["NSL-KDD Traffic"]
        HDFS["HDFS Logs"]
        Config["Config Repo Commits"]
    end

    subgraph Normalization["Ingestion & Normalization"]
        Events["Normalized Events<br/>(core/events.py)"]
        Kafka["Kafka Event Bus"]
    end

    subgraph Processing["Detection & Contextualization"]
        Detectors["Ensemble Detectors<br/>(IForest, Kitsune, ML Bridge)"]
        Topology["Neo4j Topology<br/>(Dependency Mapping)"]
        RAG["Qdrant GraphRAG<br/>(Similar SOP Retrieval)"]
    end

    subgraph Decision["Causal Analysis"]
        Window["5-Minute Slicing Window"]
        Causal["Causal Scoring Engine<br/>(rca/engine.py)"]
        LangGraph["LangGraph Workflow<br/>(8-Agent Diagnostic Path)"]
    end

    subgraph Persistence["Storage & Exporter"]
        DB[(PostgreSQL Ledger & Audit)]
        PDF["ReportLab PDF Generator"]
        MinIO[(MinIO PDF Storage)]
    end

    subgraph UserInterface["Presentation & Interaction"]
        API["FastAPI REST & Socket.IO Websockets"]
        LLM["Gemini Narratives & Chat (On-Demand)"]
        UI["Next.js Operations Dashboard"]
    end

    RawData --> Events
    Events --> Kafka
    Kafka --> Detectors
    
    Detectors & Topology & RAG --> Window
    Window --> Causal
    Causal --> LangGraph
    
    LangGraph --> DB
    LangGraph --> PDF
    PDF --> MinIO
    
    LangGraph & DB & MinIO --> API
    API --> UI
    API <--> LLM
    UI <--> LLM
```

---

## Use Cases

### 1. Configuration Change Root-Cause Analysis
**Scenario**: A network administrator commits a routing table change (`gw-1 → gw-2`). Within seconds, downstream services experience anomalous traffic patterns.

**Vajra RCA Response**:
- Detects the temporal correlation (config change < 5s before anomaly onset → +30 causal score)
- Traces the dependency path from the changed node to the affected services via Neo4j
- Ranks "Configuration change on X" as the #1 hypothesis with confirmed evidence (the real git diff)
- Demotes concurrent attack traffic to "correlated" (same window, not proven causal)
- Flags missing telemetry (packet-drop data) that would further confirm propagation
- Recommends: (1) Roll back the commit [High-Impact, requires approval], (2) Validate routing table [Diagnostic], (3) Collect packet-drop metrics [Diagnostic]

### 2. Multi-Vector Attack Detection & Attribution
**Scenario**: Multiple attack categories (Exploits, DoS, Reconnaissance) converge on a single network node from the same source IP.

**Vajra RCA Response**:
- Identifies all security alerts targeting the node with source IP attribution
- Correlates unsupervised anomalies (Isolation Forest + Kitsune) with labelled attack signatures
- Maps behavioral patterns to MITRE ATT&CK (T1498 DoS, T1046 Scanning, T1041 Exfiltration)
- Computes blast radius — which downstream services would be affected if the node is compromised
- Recommends: (1) Rate-limit traffic from the source IP [Low-Risk], (2) Validate IDS rules [Diagnostic], (3) Capture host telemetry [Diagnostic]

### 3. Upstream Dependency Failure Cascading
**Scenario**: A database server experiences anomalous behavior. Downstream API gateways and microservices begin failing.

**Vajra RCA Response**:
- Detects that the upstream anomaly temporally precedes the downstream failures
- Validates the dependency path via Neo4j: `API Gateway → Database Server`
- Ranks "Upstream dependency failure" with propagation path evidence
- Identifies the full blast radius (all transitive dependents up to 4 hops)
- Recommends checking health of the upstream dependency

### 4. Anomalous Traffic Behavioral Analysis
**Scenario**: The Isolation Forest flags statistically anomalous flows with no matching attack labels or config changes.

**Vajra RCA Response**:
- Extracts per-feature z-score attribution (which features deviate most from the learned-normal baseline)
- Classifies the behavioral signature (DoS, data exfiltration, port scan, beaconing, or unclassified volumetric)
- Maps to MITRE ATT&CK if a signature matches
- Provides SHAP-based model-faithful attribution (when the `shap` package is available) or baseline-deviation fallback
- Recommends diagnostic steps tailored to the signature type

### 5. HDFS Infrastructure Log Correlation
**Scenario**: HDFS block errors or DataNode failures detected in the log stream coincide with network anomalies.

**Vajra RCA Response**:
- Parses HDFS structured logs with block-level anomaly ground truth
- Correlates error/warning log events with concurrent network flow anomalies
- Enriches the incident timeline with cross-layer events (network + logs)
- Surfaces relevant SOP (SOP-108: HDFS Log Error Escalation) via GraphRAG

### 6. Post-Incident Review & Compliance Audit
**Scenario**: A regulatory audit requires evidence that incident response followed documented procedures.

**Vajra RCA Response**:
- Full PostgreSQL audit trail with timestamps, actors, actions, and details
- Every incident preserves the complete evidence chain: confirmed, correlated, and missing
- Status lifecycle tracking (open → investigating → mitigated → resolved)
- PDF report generation with hypothesis rankings, evidence classification, and remediation steps — archived in MinIO

---

## Business Impact Analysis

Vajra RCA provides two layers of business impact analysis — both algorithmically computed from real event data, not hardcoded:

### Layer 1: Live Dashboard Metrics (Streaming)

**Module**: `Pipeline._calculate_live_impact_metrics()`, `Pipeline._calculate_live_network_metrics()`

Computes real-time business KPIs based on the sliding window event state:

| Metric | Nominal Value | Computation Method |
|---|---|---|
| **UPI Success Rate** | 99.4% | `99.4 - (threat_index × 10.0)` where threat_index = `(anomalies×2 + alerts×3.5 + critical_alerts×5) / total_flows × cause_multiplier` |
| **Card Success Rate** | 98.4% | `UPI_rate × 0.99` |
| **API Checkout Latency** | 85ms | `85 + (threat_index × 320)` ms |
| **Revenue Loss/Min** | $0 | `drop_ratio × (flows/30) × 120` — proportional to success rate drop and transaction volume |
| **TCP Packet Loss** | ~0.05% | Computed from real `sloss`/`dloss` flow attributes, scaled by degradation severity |
| **UDP Packet Loss** | ~0.12% | Computed from real flow attributes with degradation scaling |
| **TCP Buffer Delay** | ~15.2ms | Average `tcprtt × 1000` from real flow data |
| **UDP Jitter** | ~2.1ms | Average `sjit + djit` from real flow data |
| **TCP Window Size** | 65535 | Average `swin` from real flows, compressed under degradation |
| **Buffer Overflow Risk** | nominal | Classified as `nominal` / `degraded` / `critical` based on RTT and loss thresholds |

**Degradation Logic**: When an incident is active (within 25s of detection), cause-specific multipliers kick in — config changes get 2.0×, attacks get 1.5×, generic causes get 1.2×. During nominal operation, a 0.08× background noise factor applies.

### Layer 2: Per-Incident Business Impact Assessment

**Module**: `RCAEngine._calculate_business_impact()`

Each incident carries a dedicated business impact assessment:

- **Severity Factor**: Derived from blast radius count — `min(1.0, max(0.2, (blast_count × 0.15) + 0.2))`
- **Dynamic KPIs**: Success rate, latency, throughput, and revenue loss all scale with the severity factor
- **Protocol Impact**: TCP/UDP loss, buffer delay, jitter, and window size scaled by the severity factor
- **Cause-Specific Narratives**: Different root cause kinds produce different business impact descriptions:
  - *Config change*: "Configuration update on X created downstream performance bottleneck, dropping payment success rate to Y%"
  - *Attack*: "External security signal anomaly on X disrupted transaction processing queue"
  - *Upstream failure*: "Cascading topology degradation originating from X affected database connection pool"
- **Affected Business Flow**: Automatically identified — Checkout → Payment Gateway, External API Ingestion, or Internal Transaction Processing

---

## Tech Stack

### Backend

| Technology | Version | Purpose |
|---|---|---|
| **Python** | 3.12 | Core runtime (pinned for ML wheel compatibility) |
| **FastAPI** | ≥0.115 | REST API framework with automatic OpenAPI docs |
| **Socket.IO** | python-socketio ≥5.11 | Real-time bidirectional event streaming |
| **Uvicorn** | ≥0.32 | ASGI server (standard extras for HTTP/2, WebSocket) |
| **Pydantic** | ≥2.9 | Data validation, settings management |
| **pandas** | ≥2.2 | Dataset loading, feature engineering |
| **scikit-learn** | ≥1.5 | Isolation Forest anomaly detection |
| **NumPy** | ≥2.0 | Numerical computing (Kitsune autoencoders) |
| **SHAP** | ≥0.44 | Model-faithful feature attribution (optional) |
| **LangGraph** | ≥0.1 | Multi-agent workflow orchestration |
| **Neo4j Driver** | ≥5.14 | Dependency graph (Cypher queries) |
| **asyncpg** | ≥0.29 | Async PostgreSQL driver |
| **Qdrant Client** | ≥1.6 | Vector similarity search |
| **aiokafka** | ≥0.8 | Async Apache Kafka producer/consumer |
| **Google GenAI** | ≥0.3 | Gemini API (optional, on-demand only) |
| **ReportLab** | ≥4.1 | PDF report generation |
| **MinIO** | ≥7.2 | Object storage client |
| **NetworkX** | ≥3.3 | Graph algorithms (supplementary) |

### Frontend

| Technology | Version | Purpose |
|---|---|---|
| **Next.js** | 16.2 | React framework (App Router, Server Components) |
| **React** | 19.2 | UI library |
| **TypeScript** | ≥5 | Type safety |
| **TailwindCSS** | 4 | Utility-first CSS |
| **@xyflow/react** | ≥12.11 | Interactive topology graph visualization |
| **Recharts** | ≥3.9 | Live signal rate charts |
| **socket.io-client** | ≥4.8 | Real-time event streaming |
| **Lucide React** | ≥1.24 | Icon library |

### Infrastructure (Docker Compose)

| Service | Image | Port | Purpose |
|---|---|---|---|
| **PostgreSQL** | `postgres:15-alpine` | 5432 | Incident ledger + audit trail |
| **Neo4j** | `neo4j:5.12` | 7474, 7687 | Dependency topology graph |
| **Qdrant** | `qdrant/qdrant:latest` | 6333, 6334 | Vector similarity search (SOPs/runbooks) |
| **Apache Kafka** | `confluentinc/cp-kafka:7.4.0` | 9092 | Event bus (KRaft mode, no ZooKeeper) |
| **Elasticsearch** | `elasticsearch:8.10.2` | 9200 | Log/event indexing (OTel sink) |
| **Prometheus** | `prom/prometheus:latest` | 9090 | Metrics scraping |
| **Grafana** | `grafana/grafana:latest` | 3001 | Observability dashboards |
| **MinIO** | `minio/minio:latest` | 9000, 9001 | Object storage (PDF reports) |
| **OTel Collector** | `otel/opentelemetry-collector-contrib` | 4317, 4318 | Telemetry pipeline |

---

## Project Structure

```
vajra-rca/
│
├── backend/                        # Python 3.12 backend
│   ├── app/
│   │   ├── main.py                 # FastAPI + Socket.IO ASGI entrypoint (266 lines)
│   │   ├── pipeline.py             # Live replay orchestrator + business impact (572 lines)
│   │   │
│   │   ├── core/
│   │   │   ├── config.py           # Central configuration (Pydantic Settings, dataset paths)
│   │   │   ├── events.py           # Unified event schema + Kafka event bus
│   │   │   └── serialize.py        # NumPy/pandas → JSON serializer
│   │   │
│   │   ├── ingestion/
│   │   │   ├── unsw.py             # UNSW-NB15 raw flow ingestion (49 columns)
│   │   │   ├── nsl_kdd.py          # NSL-KDD labelled traffic ingestion
│   │   │   ├── hdfs.py             # HDFS structured log ingestion
│   │   │   ├── config_monitor.py   # Real git-backed configuration change monitor
│   │   │   ├── vajra_bridge.py     # ML model bridge for pre-trained classifiers
│   │   │   └── schema.py           # Column schemas, port→role mapping, numeric features
│   │   │
│   │   ├── detection/
│   │   │   ├── isolation_forest.py # Unsupervised anomaly detection (IsolationForest)
│   │   │   ├── kitsune.py          # Online Kitsune autoencoder ensemble (NDSS 2018)
│   │   │   └── signatures.py       # MITRE ATT&CK behavioral signature classifier
│   │   │
│   │   ├── graph/
│   │   │   └── topology.py         # Neo4j dependency graph (build, traverse, serialize)
│   │   │
│   │   ├── agents/
│   │   │   ├── graph.py            # LangGraph 8-agent workflow definition
│   │   │   ├── nodes.py            # Individual agent node implementations
│   │   │   └── state.py            # Shared AgentState TypedDict schema
│   │   │
│   │   ├── rca/
│   │   │   ├── engine.py           # Correlation & Causal Inference engine (578 lines)
│   │   │   └── scoring.py          # Decomposable scoring weights + evidence taxonomy
│   │   │
│   │   ├── rag/
│   │   │   ├── graphrag.py         # GraphRAG client (Qdrant + Neo4j enrichment)
│   │   │   └── qdrant.py           # Qdrant vector store + 8 SOP seeds + keyword fallback
│   │   │
│   │   ├── llm/
│   │   │   └── gemini.py           # Gemini explanation/chat + deterministic fallback
│   │   │
│   │   ├── db/
│   │   │   └── store.py            # PostgreSQL incident ledger + audit trail
│   │   │
│   │   └── utils/
│   │       └── reporter.py         # PDF report generator + MinIO uploader
│   │
│   ├── tests/                      # pytest test suite
│   │   ├── test_anomaly_event.py
│   │   ├── test_attribution.py
│   │   ├── test_behavioral_hypothesis.py
│   │   ├── test_shap_endpoint.py
│   │   └── test_signatures.py
│   │
│   ├── scripts/
│   │   └── validate_detector.py    # Isolation Forest quality validation
│   │
│   ├── pyproject.toml              # Python dependencies & build config
│   └── .env.example                # Environment variable template
│
├── frontend/                       # Next.js 16 dashboard
│   ├── src/
│   │   ├── app/
│   │   │   ├── page.tsx            # Main dashboard page (372 lines)
│   │   │   ├── layout.tsx          # Root layout
│   │   │   └── globals.css         # Global styles
│   │   ├── components/
│   │   │   ├── IncidentDetail.tsx   # Full incident detail panel (30KB)
│   │   │   ├── TopologyGraph.tsx    # React Flow topology visualization
│   │   │   ├── MetricsChart.tsx     # Recharts signal rate chart
│   │   │   ├── AgentPipeline.tsx    # 8-agent progress stepper
│   │   │   └── ui.tsx              # Shared UI components
│   │   └── lib/
│   │       ├── api.ts              # REST API client (typed)
│   │       ├── socket.ts           # Socket.IO hook
│   │       └── types.ts            # TypeScript interfaces
│   ├── package.json
│   └── tsconfig.json
│
├── scripts/
│   ├── dataset_validation.py       # E2E Isolation Forest validation (UNSW + NSL-KDD)
│   └── verify_e2e.py              # End-to-end system verification
│
├── docs/
│   ├── architecture.md             # System architecture documentation
│   ├── system-features.md          # Feature layer documentation
│   └── demo-runbook.md             # Demo execution guide
│
├── infra/
│   ├── prometheus.yml              # Prometheus scrape configuration
│   ├── otel-collector.yaml         # OpenTelemetry Collector config
│   └── grafana/                    # Grafana provisioning & dashboards
│
├── docker-compose.yml              # 9-service infrastructure stack
├── dev.sh                          # One-command dev startup script
└── README.md                       # This file
```

---

## How to Run the Project

### Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| **Docker Desktop** | Latest | Runs 9 infrastructure services (~8GB images) |
| **Python** | 3.12.x | Pinned for ML wheel compatibility (3.14 lacks some) |
| **Node.js** | 20+ | Frontend runtime |
| **npm** | 10+ | Frontend package manager |
| **uv** | Latest | Fast Python env/installer (recommended, not required) |
| **Disk Space** | ~30GB+ | ~24GB datasets + ~8GB Docker images |

### Step 1: Prepare Datasets

Place the real datasets at `../datasets` relative to the project root:

```
TechM_Code/
├── datasets/
│   ├── KDDTrain+/
│   │   ├── KDDTrain+.txt
│   │   └── KDDTest+.txt
│   ├── UNSW_NB15/
│   │   ├── UNSW-NB15_1.csv
│   │   ├── UNSW-NB15_2.csv
│   │   ├── UNSW-NB15_3.csv
│   │   ├── UNSW-NB15_4.csv
│   │   ├── NUSW-NB15_features.csv
│   │   ├── UNSW_NB15_training-set.csv
│   │   └── UNSW_NB15_testing-set.csv
│   └── HDFS/
│       ├── HDFS_2k/
│       │   └── HDFS_2k.log_structured.csv
│       └── HDFS_v1/
│           └── preprocessed/
│               └── anomaly_label.csv
└── vajra-rca/    ← (this project)
```

Override the location: `export VAJRA_DATASETS_DIR=/absolute/path/to/datasets`

### Step 2: Start Infrastructure

```bash
# From the project root
docker compose up -d

# Wait for all services to become healthy (~60-90 seconds)
docker compose ps
```

All 9 services should show `healthy` status:
- PostgreSQL (5432)
- Neo4j (7474/7687)
- Qdrant (6333/6334)
- Kafka (9092)
- Elasticsearch (9200)
- Prometheus (9090)
- Grafana (3001)
- MinIO (9000/9001)
- OTel Collector (4317/4318)

### Step 3: Start the Backend

```bash
cd backend

# Create virtual environment (Python 3.12)
uv venv --python 3.12 .venv

# Install dependencies
uv pip install --python .venv/bin/python -e .

# Copy and configure environment
cp .env.example .env
# Edit .env to set VAJRA_GOOGLE_API_KEY (optional)

# Start the API server
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

**Startup sequence** (takes ~15-30 seconds):
1. Connects to PostgreSQL → creates `incidents` and `audit_log` tables
2. Connects to Qdrant → seeds 8 SOPs into the `vajra_sop` collection
3. Connects to Kafka → starts producer/consumer (or falls back to in-memory)
4. Loads UNSW-NB15 flows → builds Neo4j topology → fits Isolation Forest
5. Loads HDFS logs and anomaly labels

Verify readiness:
```bash
curl http://localhost:8000/api/health
# → {"status": "ok", "ready": true}

curl http://localhost:8000/api/status
# → Full status with topology stats, detector report, etc.
```

### Step 4: Start the Frontend

```bash
cd frontend

# Install dependencies
npm install

# Start the development server
npm run dev
```

Open **http://localhost:3000** in your browser.

**Login credentials**: `admin` / `admin`

### Step 5: Trigger the Flagship Incident

Click **"Inject Config Change"** in the dashboard header (or call the API):

```bash
curl -X POST http://localhost:8000/api/inject/config-change \
  -H "Content-Type: application/json" \
  -d '{"node": null}'
```

This:
1. Makes a **real git commit** to `backend/var/demo-config/routing.yaml` (reroute default gateway)
2. Streams real malicious/anomalous UNSW flows for the affected node
3. Runs all three detectors (Isolation Forest + Kitsune + Vajra ML) on the impact flows
4. Executes the full 8-agent LangGraph pipeline (visible as live steps in the UI)
5. Produces a ranked incident where the config change is the #1 hypothesis with confirmed evidence

### One-Command Startup (Alternative)

```bash
# Start both backend and frontend simultaneously
./dev.sh
```

### Optional: Enable Gemini Explanations

```bash
export VAJRA_GOOGLE_API_KEY=your_gemini_api_key
```

Without a key, the system is fully functional — explanations and chat use a deterministic generator. With a key, `POST /api/incidents/{id}/explain` generates richer Gemini narratives, and `/api/incidents/{id}/chat` enables conversational Q&A.

---

## API Reference

### Health & Status

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Health check (`{"status": "ok", "ready": true}`) |
| `GET` | `/api/status` | Full pipeline status (detector report, topology stats, DB stats) |

### Metrics & Topology

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/metrics` | Live signal counters, rates, business impact, Kitsune stats |
| `GET` | `/api/topology?top_n=60` | Dependency graph (nodes + edges) for visualization |
| `GET` | `/api/topology/node/{node}` | Node detail: role, flows, upstream, downstream, blast radius |

### Incidents

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/incidents?limit=100` | List incidents (summary: ID, title, severity, status, confidence) |
| `GET` | `/api/incidents/{id}` | Full incident (hypotheses, evidence, timeline, business impact) |
| `GET` | `/api/incidents/{id}/audit` | Audit trail for this incident |
| `GET` | `/api/incidents/{id}/attribution` | SHAP / baseline-deviation feature attribution |
| `GET` | `/api/incidents/{id}/similar` | GraphRAG: topology-aware similar SOPs/runbooks |
| `POST` | `/api/incidents/{id}/explain` | Generate Gemini / deterministic explanation |
| `POST` | `/api/incidents/{id}/chat` | Grounded Q&A about the incident |
| `POST` | `/api/incidents/{id}/report` | Generate PDF report and upload to MinIO |
| `POST` | `/api/incidents/{id}/status` | Update status (open/investigating/mitigated/resolved) |

### Operations

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/inject/config-change` | Make a real config commit and correlate |
| `GET` | `/api/telemetry/replay/status` | Check if telemetry replay is active |
| `POST` | `/api/telemetry/replay/toggle` | Start/stop live dataset replay |
| `GET` | `/api/detectors/status` | Status of all detectors (Kitsune warmup, IForest fit, HDFS) |
| `POST` | `/api/rag/reseed` | Force-reseed Qdrant SOP collection |
| `GET` | `/api/audit?limit=200` | Global audit trail |

### Socket.IO Events

| Event | Direction | Payload |
|---|---|---|
| `metrics` | Server → Client | Live counters, rates, business impact |
| `incident` | Server → Client | New incident created |
| `alert` | Server → Client | Security alert event |
| `anomaly` | Server → Client | Anomaly detection event |
| `config_change` | Server → Client | Configuration change event |
| `agent_step` | Server → Client | Per-agent progress (`{node, focal_node, ts}`) |

---

## Detection & ML Pipeline

### Isolation Forest Validation

Run the dataset validation script to measure real precision/recall/F1:

```bash
cd backend && .venv/bin/python -m scripts.validate_detector
```

Or the full cross-dataset validation:

```bash
python scripts/dataset_validation.py --datasets-dir /path/to/datasets
```

This fits the Isolation Forest on benign training samples (unsupervised) and evaluates against real labelled test splits — producing precision, recall, F1, and ROC-AUC for both UNSW-NB15 and NSL-KDD.

### SHAP Attribution

When the `shap` package is available, `Pipeline.shap_attribution()` provides model-faithful TreeExplainer attribution for a node's anomalous flows. If unavailable, it falls back to baseline-deviation attribution using z-scores from the StandardScaler.

---

## Multi-Agent RCA Pipeline

The LangGraph pipeline executes in a worker thread with streaming updates:

```python
# Executed by Pipeline._run_agents()
for step in agent_graph.stream(initial_state, stream_mode="updates"):
    for node_name, update in step.items():
        state.update(update)
        emit("agent_step", {"node": node_name, "focal_node": node})
```

Each agent enriches the shared `AgentState`:
- **Coordinator**: Bounds events → `raw_events`
- **Metric**: Aggregates → `metrics`
- **Log**: Filters errors → `logs`
- **Trace**: Extracts spans → `traces`
- **Graph**: Queries Neo4j → `dependencies`
- **RAG**: Searches Qdrant+Neo4j → `rag_documents`
- **Root Cause**: Runs RCAEngine → `hypotheses`
- **Report**: Synthesizes → `final_report`

---

## Configuration Reference

All settings are environment variables prefixed `VAJRA_` (managed via Pydantic Settings):

| Variable | Default | Description |
|---|---|---|
| `VAJRA_DATASETS_DIR` | `../datasets` | Location of the real datasets |
| `VAJRA_GOOGLE_API_KEY` | — | Google Gemini API key (optional) |
| `VAJRA_GEMINI_MODEL` | `gemini-2.5-pro` | Gemini model for explanations/chat |
| `VAJRA_CORRELATION_WINDOW_S` | `300` | Incident correlation window (seconds) |
| `VAJRA_CONFIG_CAUSAL_WINDOW_S` | `5` | Config change causal bonus window (seconds) |
| `VAJRA_IFOREST_CONTAMINATION` | `0.1` | Isolation Forest contamination parameter |
| `VAJRA_IFOREST_MAX_TRAIN_ROWS` | `40000` | Cap training rows for fast fits |
| `VAJRA_REPLAY_SPEED` | `60.0` | Dataset timestamp compression factor |
| `VAJRA_HOST` | `0.0.0.0` | API server host |
| `VAJRA_PORT` | `8000` | API server port |
| `VAJRA_POSTGRES_URL` | `postgresql://postgres:postgres@localhost:5432/vajra_rca` | PostgreSQL connection |
| `VAJRA_NEO4J_URI` | `bolt://localhost:7687` | Neo4j connection |
| `VAJRA_NEO4J_USER` / `_PASSWORD` | `neo4j` / `password` | Neo4j credentials |
| `VAJRA_QDRANT_HOST` / `_PORT` | `localhost` / `6333` | Qdrant connection |
| `VAJRA_KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | Kafka bootstrap servers |
| `VAJRA_MINIO_ENDPOINT` | `localhost:9000` | MinIO endpoint |
| `VAJRA_MINIO_ACCESS_KEY` / `_SECRET_KEY` | `minioadmin` / `minioadmin` | MinIO credentials |

Frontend: Set `NEXT_PUBLIC_API_URL` in `frontend/.env.local` (default: `http://localhost:8000`).

---

## Testing

```bash
cd backend

# Run all tests
.venv/bin/pytest tests/ -v

# Individual test files
.venv/bin/pytest tests/test_signatures.py -v        # Behavioral signature classification
.venv/bin/pytest tests/test_attribution.py -v       # Feature attribution logic
.venv/bin/pytest tests/test_behavioral_hypothesis.py -v  # Behavioral hypothesis generation
.venv/bin/pytest tests/test_anomaly_event.py -v     # Anomaly event construction
.venv/bin/pytest tests/test_shap_endpoint.py -v     # SHAP attribution endpoint

# Dataset validation (produces docs/validation_results.md)
.venv/bin/python scripts/dataset_validation.py

# Detector validation
.venv/bin/python -m scripts.validate_detector

# End-to-end verification
python scripts/verify_e2e.py
```

---

## Roadmap

| Status | Feature |
|---|---|
| Done | Neo4j dependency topology graph |
| Done | Apache Kafka event bus (with in-memory fallback) |
| Done | PostgreSQL incident ledger + audit trail |
| Done | Qdrant + Neo4j GraphRAG (topology-aware SOP retrieval) |
| Done | LangGraph 8-agent multi-agent RCA pipeline |
| Done | Kitsune online autoencoder detection |
| Done | Vajra ML model bridge (sklearn/joblib classifiers) |
| Done | MITRE ATT&CK behavioral signature mapping |
| Done | SHAP + baseline-deviation feature attribution |
| Done | Real-time business impact metrics (live + per-incident) |
| Done | PDF report generation + MinIO archival |
| Done | Gemini narrative explanation + grounded chat |
| Done | Next.js real-time dashboard with Socket.IO |
| Planned | OpenTelemetry SDK instrumentation for the backend |
| Planned | Prometheus `/metrics` endpoint (Prometheus-format) |
| Planned | Grafana dashboard auto-provisioning with live backend metrics |
| Planned | Elasticsearch log indexing from OTel Collector |

> **Note**: Prometheus is configured to scrape `host.docker.internal:8000` and the OTel Collector is configured to export to Prometheus/Elasticsearch — but the backend does not yet emit OpenTelemetry traces or Prometheus-format metrics. These services run but carry no application telemetry until instrumented.

---

<div align="center">

**Built for the Network Anomaly Root-Cause Assistant Challenge**

*Vajra (वज्र) — Sanskrit for "thunderbolt" or "diamond" — symbolizing both the speed of detection and the unbreakable transparency of evidence.*

</div>
