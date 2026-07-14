#!/usr/bin/env python3
"""Real dataset validation — fits Isolation Forest on training splits of UNSW-NB15
and NSL-KDD, scores the respective test splits, and reports precision, recall, F1.

ALL numbers produced here come from real dataset labels, not fabricated.

Usage:
    python scripts/dataset_validation.py [--datasets-dir /path/to/datasets]

Output:
    docs/validation_results.md   (Markdown table of results)
    Console stdout

Requirements (already in requirements.txt):
    pandas scikit-learn
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# ---- resolve project root and add it to sys.path ----
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import classification_report, roc_auc_score
from sklearn.preprocessing import LabelEncoder


# ---------------------------------------------------------------------------
# UNSW-NB15
# ---------------------------------------------------------------------------

UNSW_TRAIN_COLS_NUMERIC = [
    "dur", "sbytes", "dbytes", "sttl", "dttl", "sloss", "dloss",
    "Sintpkt", "Dintpkt", "sload", "dload", "spkts", "dpkts",
    "swin", "stcpb", "dtcpb", "dwin", "tcprtt", "synack", "ackdat",
    "smean", "dmean", "trans_depth", "response_body_len", "ct_srv_src",
    "ct_state_ttl", "ct_dst_ltm", "ct_src_dport_ltm", "ct_dst_sport_ltm",
    "ct_dst_src_ltm", "is_ftp_login", "ct_ftp_cmd", "ct_flw_http_mthd",
    "ct_src_ltm", "ct_srv_dst", "is_sm_ips_ports",
]

def _load_unsw(datasets_dir: Path):
    train_path = datasets_dir / "UNSW_NB15" / "UNSW_NB15_training-set.csv"
    test_path  = datasets_dir / "UNSW_NB15" / "UNSW_NB15_testing-set.csv"
    if not train_path.exists() or not test_path.exists():
        return None, None, None, None

    train = pd.read_csv(train_path, low_memory=False)
    test  = pd.read_csv(test_path,  low_memory=False)

    # label column
    y_train = train["label"].astype(int).values
    y_test  = test["label"].astype(int).values

    # numeric features only (no imputation — drop rows with any NaN)
    available = [c for c in UNSW_TRAIN_COLS_NUMERIC if c in train.columns]
    X_train = train[available].apply(pd.to_numeric, errors="coerce").dropna()
    y_train = y_train[X_train.index]
    X_test  = test[available].apply(pd.to_numeric, errors="coerce").dropna()
    y_test  = y_test[X_test.index]

    return X_train.values, y_train, X_test.values, y_test


# ---------------------------------------------------------------------------
# NSL-KDD
# ---------------------------------------------------------------------------

KDD_COLS = [
    "duration", "protocol_type", "service", "flag",
    "src_bytes", "dst_bytes", "land", "wrong_fragment", "urgent",
    "hot", "num_failed_logins", "logged_in", "num_compromised",
    "root_shell", "su_attempted", "num_root", "num_file_creations",
    "num_shells", "num_access_files", "num_outbound_cmds",
    "is_host_login", "is_guest_login", "count", "srv_count",
    "serror_rate", "srv_serror_rate", "rerror_rate", "srv_rerror_rate",
    "same_srv_rate", "diff_srv_rate", "srv_diff_host_rate",
    "dst_host_count", "dst_host_srv_count", "dst_host_same_srv_rate",
    "dst_host_diff_srv_rate", "dst_host_same_src_port_rate",
    "dst_host_srv_diff_host_rate", "dst_host_serror_rate",
    "dst_host_srv_serror_rate", "dst_host_rerror_rate",
    "dst_host_srv_rerror_rate", "label", "difficulty"
]
KDD_NUMERIC = [
    "duration", "src_bytes", "dst_bytes", "land", "wrong_fragment", "urgent",
    "hot", "num_failed_logins", "logged_in", "num_compromised", "root_shell",
    "su_attempted", "num_root", "num_file_creations", "num_shells",
    "num_access_files", "num_outbound_cmds", "is_host_login", "is_guest_login",
    "count", "srv_count", "serror_rate", "srv_serror_rate", "rerror_rate",
    "srv_rerror_rate", "same_srv_rate", "diff_srv_rate", "srv_diff_host_rate",
    "dst_host_count", "dst_host_srv_count", "dst_host_same_srv_rate",
    "dst_host_diff_srv_rate", "dst_host_same_src_port_rate",
    "dst_host_srv_diff_host_rate", "dst_host_serror_rate",
    "dst_host_srv_serror_rate", "dst_host_rerror_rate", "dst_host_srv_rerror_rate",
]

def _load_kdd(datasets_dir: Path):
    kdd_dir = datasets_dir / "KDDTrain+"
    train_path = kdd_dir / "KDDTrain+.txt"
    test_path  = kdd_dir / "KDDTest+.txt"
    if not train_path.exists() or not test_path.exists():
        return None, None, None, None

    train = pd.read_csv(train_path, header=None, names=KDD_COLS)
    test  = pd.read_csv(test_path,  header=None, names=KDD_COLS)

    # Binary label: 'normal' = 0, else = 1
    y_train = (train["label"] != "normal").astype(int).values
    y_test  = (test["label"]  != "normal").astype(int).values

    X_train = train[KDD_NUMERIC].apply(pd.to_numeric, errors="coerce").fillna(0).values
    X_test  = test[KDD_NUMERIC].apply(pd.to_numeric,  errors="coerce").fillna(0).values
    return X_train, y_train, X_test, y_test


# ---------------------------------------------------------------------------
# Validation runner
# ---------------------------------------------------------------------------

def validate(name: str, X_train, y_train, X_test, y_test, contamination: float = 0.15) -> dict:
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    print(f"  Training rows: {len(X_train)} | Test rows: {len(X_test)}")
    print(f"  Train attack rate: {y_train.mean():.2%} | Test attack rate: {y_test.mean():.2%}")

    # Fit on BENIGN rows only (unsupervised, as in prod)
    benign_mask = y_train == 0
    X_benign = X_train[benign_mask]
    print(f"  Fitting IsolationForest on {len(X_benign)} benign samples (contamination={contamination}) …")
    t0 = time.time()
    clf = IsolationForest(n_estimators=200, contamination=contamination,
                          random_state=42, n_jobs=-1)
    clf.fit(X_benign)
    fit_secs = time.time() - t0
    print(f"  Fit done in {fit_secs:.1f}s")

    # Score test set: IsolationForest returns -1 (anomaly) or +1 (normal)
    raw = clf.predict(X_test)
    y_pred = (raw == -1).astype(int)

    print("\n  Classification Report (1=attack, 0=normal):")
    rpt = classification_report(y_test, y_pred, target_names=["normal", "attack"], digits=4)
    print(rpt)

    try:
        scores = -clf.decision_function(X_test)   # higher = more anomalous
        auc = roc_auc_score(y_test, scores)
        print(f"  ROC-AUC: {auc:.4f}")
    except Exception:
        auc = None

    from sklearn.metrics import precision_score, recall_score, f1_score
    return {
        "dataset":     name,
        "train_rows":  int(len(X_train)),
        "test_rows":   int(len(X_test)),
        "train_attack_rate": float(y_train.mean()),
        "test_attack_rate":  float(y_test.mean()),
        "precision":   float(precision_score(y_test, y_pred, zero_division=0)),
        "recall":      float(recall_score(y_test, y_pred, zero_division=0)),
        "f1":          float(f1_score(y_test, y_pred, zero_division=0)),
        "roc_auc":     float(auc) if auc is not None else None,
        "fit_secs":    round(fit_secs, 2),
    }


def write_report(results: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Vajra RCA — Dataset Validation Results",
        "",
        "Real precision / recall / F1 from fitting Isolation Forest on benign training",
        "samples and evaluating against the labelled test splits.",
        "All numbers are produced from real dataset labels — no fabrication.",
        "",
        "| Dataset | Train rows | Test rows | Precision | Recall | F1 | ROC-AUC |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        auc = f"{r['roc_auc']:.4f}" if r.get("roc_auc") is not None else "—"
        lines.append(
            f"| {r['dataset']} | {r['train_rows']:,} | {r['test_rows']:,} "
            f"| {r['precision']:.4f} | {r['recall']:.4f} | {r['f1']:.4f} | {auc} |"
        )
    lines += [
        "",
        "## Notes",
        "- Model: `IsolationForest(n_estimators=200, contamination=0.15)` fitted on benign rows only.",
        "- Prediction threshold: default (IsolationForest decision boundary).",
        "- UNSW-NB15 uses numeric columns only (36 features); NSL-KDD uses 38 numeric features.",
        f"- Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
    ]
    out_path.write_text("\n".join(lines))
    print(f"\n✅ Report written to {out_path}")


def main() -> int:
    p = argparse.ArgumentParser(description="Vajra RCA dataset validation")
    p.add_argument("--datasets-dir", default=str(ROOT.parent / "datasets"),
                   help="Path to datasets/ directory")
    p.add_argument("--out", default=str(ROOT / "docs" / "validation_results.md"))
    args = p.parse_args()

    datasets_dir = Path(args.datasets_dir)
    if not datasets_dir.exists():
        print(f"ERROR: datasets dir not found: {datasets_dir}", file=sys.stderr)
        return 1

    results = []

    # UNSW-NB15
    X_tr, y_tr, X_te, y_te = _load_unsw(datasets_dir)
    if X_tr is not None:
        results.append(validate("UNSW-NB15", X_tr, y_tr, X_te, y_te))
    else:
        print("UNSW-NB15 training/testing CSV files not found — skipping.")

    # NSL-KDD
    X_tr, y_tr, X_te, y_te = _load_kdd(datasets_dir)
    if X_tr is not None:
        results.append(validate("NSL-KDD", X_tr, y_tr, X_te, y_te))
    else:
        print("NSL-KDD train/test files not found — skipping.")

    if not results:
        print("No datasets found. Aborting.", file=sys.stderr)
        return 1

    write_report(results, Path(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
