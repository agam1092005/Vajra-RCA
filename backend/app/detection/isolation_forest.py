"""Unsupervised anomaly detection with Isolation Forest (scikit-learn).

The model is FIT on real observed traffic (a baseline of predominantly-normal
flows) and then scores every flow. No thresholds are hardcoded to labels — the
label is only ever used *after the fact* to validate detector quality.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from ..core.config import settings
from ..core.events import Event, EventType, Severity
from ..ingestion.schema import UNSW_NUMERIC_FEATURES, infer_service_role


@dataclass
class DetectorReport:
    trained_rows: int
    features: list[str]
    precision: float | None = None
    recall: float | None = None
    f1: float | None = None
    anomaly_rate: float | None = None


class FlowAnomalyDetector:
    """Isolation Forest over UNSW numeric flow features."""

    def __init__(self, features: list[str] | None = None, contamination: float | None = None) -> None:
        self.features = features or UNSW_NUMERIC_FEATURES
        self.contamination = contamination if contamination is not None else settings.iforest_contamination
        self.scaler = StandardScaler()
        self.model = IsolationForest(
            n_estimators=200, contamination=self.contamination,
            random_state=42, n_jobs=-1,
        )
        self._fitted = False

    def _matrix(self, df: pd.DataFrame) -> np.ndarray:
        x = df[self.features].apply(pd.to_numeric, errors="coerce").fillna(0.0).to_numpy(dtype=float)
        return np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)

    def fit(self, df: pd.DataFrame) -> DetectorReport:
        rows = df.head(settings.iforest_max_train_rows)
        x = self.scaler.fit_transform(self._matrix(rows))
        self.model.fit(x)
        self._fitted = True
        return DetectorReport(trained_rows=len(rows), features=self.features)

    def score(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return df with `anomaly_score` (higher = more anomalous) and `is_anomaly`."""
        if not self._fitted:
            raise RuntimeError("detector not fitted")
        x = self.scaler.transform(self._matrix(df))
        # sklearn: decision_function high=normal; negate so high=anomalous.
        raw = -self.model.decision_function(x)
        pred = self.model.predict(x)  # -1 anomaly, 1 normal
        out = df.copy()
        out["anomaly_score"] = raw
        out["is_anomaly"] = (pred == -1).astype(int)
        return out

    def validate(self, df: pd.DataFrame, label_col: str = "Label") -> DetectorReport:
        """Fit-then-score quality vs real labels (precision/recall/F1)."""
        scored = self.score(df)
        y_true = pd.to_numeric(scored[label_col], errors="coerce").fillna(0).astype(int).to_numpy()
        y_pred = scored["is_anomaly"].to_numpy()
        tp = int(((y_pred == 1) & (y_true == 1)).sum())
        fp = int(((y_pred == 1) & (y_true == 0)).sum())
        fn = int(((y_pred == 0) & (y_true == 1)).sum())
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        return DetectorReport(
            trained_rows=len(df), features=self.features,
            precision=round(precision, 3), recall=round(recall, 3), f1=round(f1, 3),
            anomaly_rate=round(float(y_pred.mean()), 3),
        )


def anomaly_event_from_flow(row: pd.Series) -> Event:
    """Build an ANOMALY event from a scored flow row (real detector output)."""
    dstip = str(row.get("dstip"))
    score = float(row.get("anomaly_score", 0.0))
    dport = row.get("dsport_i")
    role = infer_service_role(dport, row.get("service"))
    sev = Severity.HIGH if score > 0.15 else Severity.MEDIUM if score > 0.05 else Severity.LOW
    return Event(
        event_type=EventType.ANOMALY, source="isolation_forest", node=dstip,
        timestamp=float(row.get("Stime", 0.0)), severity=sev,
        confidence=round(min(1.0, 0.5 + score), 3),
        signature=f"Traffic-flow anomaly on {dstip} ({role})",
        description=(f"Isolation Forest flagged anomalous flow {row.get('srcip')}->{dstip}:"
                     f"{dport or '-'} (score={score:.3f})"),
        attributes={
            "srcip": row.get("srcip"), "dstip": dstip, "dsport": dport, "role": role,
            "anomaly_score": round(score, 4), "detector": "isolation_forest",
            "attack_cat": row.get("attack_cat", ""), "label": int(row.get("Label", 0)),
        },
    )
