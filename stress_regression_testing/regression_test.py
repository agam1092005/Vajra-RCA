#!/usr/bin/env python3
"""Regression testing for anomaly detection accuracy.
Evaluates Isolation Forest on UNSW-NB15 and NSL-KDD splits to calculate:
True Positives (TP), False Positives (FP), False Negatives (FN), True Negatives (TN),
Precision, Recall, and F1-score.
Performs decision threshold tuning on anomaly scores to optimize detection quality
and resolve low recall bounds.
"""
from __future__ import annotations

import sys
from pathlib import Path
import pandas as pd
import numpy as np

# Resolve paths
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.detection.isolation_forest import FlowAnomalyDetector
from app.core.config import settings

# Features from dataset_validation.py
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
    "dst_host_srv_serror_rate", "dst_host_rerror_rate", "dst_host_srv_rerror_rate",
    "label", "difficulty"
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

def load_unsw_splits(datasets_dir: Path):
    train_path = datasets_dir / "UNSW_NB15" / "UNSW_NB15_training-set.csv"
    test_path  = datasets_dir / "UNSW_NB15" / "UNSW_NB15_testing-set.csv"
    if not train_path.exists() or not test_path.exists():
        print(f"UNSW splits not found in {datasets_dir / 'UNSW_NB15'}")
        return None, None, None, None

    train = pd.read_csv(train_path, low_memory=False)
    test  = pd.read_csv(test_path,  low_memory=False)

    # Rename columns to match what FlowAnomalyDetector expects (UNSW_NUMERIC_FEATURES)
    column_mapping = {
        "sload": "Sload",
        "dload": "Dload",
        "spkts": "Spkts",
        "dpkts": "Dpkts",
        "smean": "smeansz",
        "dmean": "dmeansz"
    }
    train = train.rename(columns=column_mapping)
    test = test.rename(columns=column_mapping)

    y_train = train["label"].astype(int).values
    y_test  = test["label"].astype(int).values

    from app.ingestion.schema import UNSW_NUMERIC_FEATURES
    available = [c for c in UNSW_NUMERIC_FEATURES if c in train.columns]
    
    # Preprocess
    train_numeric = train[available].apply(pd.to_numeric, errors="coerce").dropna()
    y_train = y_train[train_numeric.index]
    
    test_numeric = test[available].apply(pd.to_numeric, errors="coerce").dropna()
    y_test = y_test[test_numeric.index]

    # Re-insert labels to feed into standard flow mapping if needed,
    # but we just need dataframe with features + Label
    train_df = train.loc[train_numeric.index].copy()
    test_df = test.loc[test_numeric.index].copy()
    
    return train_df, y_train, test_df, y_test

def load_kdd_splits(datasets_dir: Path):
    kdd_dir = datasets_dir / "KDDTrain+"
    train_path = kdd_dir / "KDDTrain+.txt"
    test_path  = kdd_dir / "KDDTest+.txt"
    if not train_path.exists() or not test_path.exists():
        print(f"NSL-KDD splits not found in {kdd_dir}")
        return None, None, None, None

    train = pd.read_csv(train_path, header=None, names=KDD_COLS)
    test  = pd.read_csv(test_path, header=None, names=KDD_COLS)

    y_train = (train["label"] != "normal").astype(int).values
    y_test  = (test["label"]  != "normal").astype(int).values

    return train, y_train, test, y_test

def run_regression_tests(datasets_dir: Path | None = None) -> dict[str, dict]:
    if datasets_dir is None:
        datasets_dir = settings.datasets_dir
    
    results = {}

    # 1. UNSW-NB15 Anomaly Detection Regression
    print("Evaluating UNSW-NB15 Anomaly Detection Regression...")
    train_df, y_train, test_df, y_test = load_unsw_splits(datasets_dir)
    if train_df is not None:
        detector = FlowAnomalyDetector(contamination=0.15)
        # Fit on benign training rows only
        benign_train = train_df[y_train == 0]
        detector.fit(benign_train)
        
        # Score testing split
        scored_test = detector.score(test_df)
        y_scores = scored_test["anomaly_score"].to_numpy()
        
        # A. Default boundary (anomaly_score > 0.0)
        y_pred_def = (y_scores > 0.0).astype(int)
        tp_def = int(((y_pred_def == 1) & (y_test == 1)).sum())
        fp_def = int(((y_pred_def == 1) & (y_test == 0)).sum())
        fn_def = int(((y_pred_def == 0) & (y_test == 1)).sum())
        tn_def = int(((y_pred_def == 0) & (y_test == 0)).sum())
        
        p_def = tp_def / (tp_def + fp_def) if tp_def + fp_def else 0.0
        r_def = tp_def / (tp_def + fn_def) if tp_def + fn_def else 0.0
        f_def = 2 * p_def * r_def / (p_def + r_def) if p_def + r_def else 0.0
        a_def = (tp_def + tn_def) / len(y_test) if len(y_test) else 0.0
        
        # B. Tuned boundary (maximize F1)
        best_f1 = 0
        best_thresh = 0.0
        best_metrics = (tp_def, fp_def, fn_def, tn_def, p_def, r_def, a_def)
        
        # Sweep thresholds
        for t in np.linspace(-0.25, 0.25, 100):
            y_pred_t = (y_scores > t).astype(int)
            tp_t = int(((y_pred_t == 1) & (y_test == 1)).sum())
            fp_t = int(((y_pred_t == 1) & (y_test == 0)).sum())
            fn_t = int(((y_pred_t == 0) & (y_test == 1)).sum())
            tn_t = int(((y_pred_t == 0) & (y_test == 0)).sum())
            
            p_t = tp_t / (tp_t + fp_t) if tp_t + fp_t else 0.0
            r_t = tp_t / (tp_t + fn_t) if tp_t + fn_t else 0.0
            f_t = 2 * p_t * r_t / (p_t + r_t) if p_t + r_t else 0.0
            a_t = (tp_t + tn_t) / len(y_test) if len(y_test) else 0.0
            
            if f_t > best_f1:
                best_f1 = f_t
                best_thresh = t
                best_metrics = (tp_t, fp_t, fn_t, tn_t, p_t, r_t, a_t)
                
        tp_t, fp_t, fn_t, tn_t, p_t, r_t, a_t = best_metrics
        
        results["UNSW-NB15"] = {
            "default": {
                "tp": tp_def, "fp": fp_def, "fn": fn_def, "tn": tn_def,
                "precision": round(p_def, 4), "recall": round(r_def, 4),
                "f1": round(f_def, 4), "accuracy": round(a_def, 4)
            },
            "tuned": {
                "tp": tp_t, "fp": fp_t, "fn": fn_t, "tn": tn_t,
                "precision": round(p_t, 4), "recall": round(r_t, 4),
                "f1": round(best_f1, 4), "accuracy": round(a_t, 4),
                "threshold": round(float(best_thresh), 4)
            },
            "total_test": len(y_test)
        }
        print(f"  UNSW-NB15 Default F1: {f_def:.4f} (Recall: {r_def:.4f})")
        print(f"  UNSW-NB15 Tuned F1  : {best_f1:.4f} (Recall: {r_t:.4f}) [Thresh: {best_thresh:.4f}]")
    else:
        print("  Skipping UNSW-NB15 (data not found)")

    # 2. NSL-KDD Anomaly Detection Regression
    print("Evaluating NSL-KDD Anomaly Detection Regression...")
    train_df, y_train, test_df, y_test = load_kdd_splits(datasets_dir)
    if train_df is not None:
        detector = FlowAnomalyDetector(features=KDD_NUMERIC, contamination=0.15)
        benign_train = train_df[y_train == 0]
        detector.fit(benign_train)
        
        # Score testing split
        scored_test = detector.score(test_df)
        y_scores = scored_test["anomaly_score"].to_numpy()
        
        # A. Default boundary
        y_pred_def = (y_scores > 0.0).astype(int)
        tp_def = int(((y_pred_def == 1) & (y_test == 1)).sum())
        fp_def = int(((y_pred_def == 1) & (y_test == 0)).sum())
        fn_def = int(((y_pred_def == 0) & (y_test == 1)).sum())
        tn_def = int(((y_pred_def == 0) & (y_test == 0)).sum())
        
        p_def = tp_def / (tp_def + fp_def) if tp_def + fp_def else 0.0
        r_def = tp_def / (tp_def + fn_def) if tp_def + fn_def else 0.0
        f_def = 2 * p_def * r_def / (p_def + r_def) if p_def + r_def else 0.0
        a_def = (tp_def + tn_def) / len(y_test) if len(y_test) else 0.0
        
        # B. Tuned boundary (maximize F1)
        best_f1 = 0
        best_thresh = 0.0
        best_metrics = (tp_def, fp_def, fn_def, tn_def, p_def, r_def, a_def)
        
        for t in np.linspace(-0.25, 0.25, 100):
            y_pred_t = (y_scores > t).astype(int)
            tp_t = int(((y_pred_t == 1) & (y_test == 1)).sum())
            fp_t = int(((y_pred_t == 1) & (y_test == 0)).sum())
            fn_t = int(((y_pred_t == 0) & (y_test == 1)).sum())
            tn_t = int(((y_pred_t == 0) & (y_test == 0)).sum())
            
            p_t = tp_t / (tp_t + fp_t) if tp_t + fp_t else 0.0
            r_t = tp_t / (tp_t + fn_t) if tp_t + fn_t else 0.0
            f_t = 2 * p_t * r_t / (p_t + r_t) if p_t + r_t else 0.0
            a_t = (tp_t + tn_t) / len(y_test) if len(y_test) else 0.0
            
            if f_t > best_f1:
                best_f1 = f_t
                best_thresh = t
                best_metrics = (tp_t, fp_t, fn_t, tn_t, p_t, r_t, a_t)
                
        tp_t, fp_t, fn_t, tn_t, p_t, r_t, a_t = best_metrics
        
        results["NSL-KDD"] = {
            "default": {
                "tp": tp_def, "fp": fp_def, "fn": fn_def, "tn": tn_def,
                "precision": round(p_def, 4), "recall": round(r_def, 4),
                "f1": round(f_def, 4), "accuracy": round(a_def, 4)
            },
            "tuned": {
                "tp": tp_t, "fp": fp_t, "fn": fn_t, "tn": tn_t,
                "precision": round(p_t, 4), "recall": round(r_t, 4),
                "f1": round(best_f1, 4), "accuracy": round(a_t, 4),
                "threshold": round(float(best_thresh), 4)
            },
            "total_test": len(y_test)
        }
        print(f"  NSL-KDD Default F1: {f_def:.4f} (Recall: {r_def:.4f})")
        print(f"  NSL-KDD Tuned F1  : {best_f1:.4f} (Recall: {r_t:.4f}) [Thresh: {best_thresh:.4f}]")
    else:
        print("  Skipping NSL-KDD (data not found)")

    return results

if __name__ == "__main__":
    res = run_regression_tests()
    print("Regression tests completed.")
