"""Validate the Isolation Forest detector against real UNSW-NB15 attack labels.

Labels are used ONLY to measure the unsupervised detector, never to drive detection.

    cd backend && .venv/bin/python -m scripts.validate_detector
"""
from __future__ import annotations

from app.detection.isolation_forest import FlowAnomalyDetector
from app.ingestion.unsw import load_unsw_raw


def main() -> None:
    df = load_unsw_raw(limit=30000)
    attacks = int(df["Label"].sum())
    print(f"Loaded {len(df):,} real UNSW-NB15 flows — {attacks:,} attacks "
          f"({attacks/len(df)*100:.1f}%)")
    det = FlowAnomalyDetector()
    det.fit(df)
    rep = det.validate(df)
    print("\nIsolation Forest (unsupervised) vs ground-truth labels:")
    print(f"  precision   = {rep.precision}")
    print(f"  recall      = {rep.recall}")
    print(f"  f1          = {rep.f1}")
    print(f"  anomaly_rate= {rep.anomaly_rate}")
    print(f"  features    = {len(rep.features)}")


if __name__ == "__main__":
    main()
