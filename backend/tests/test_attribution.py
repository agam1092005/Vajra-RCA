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
