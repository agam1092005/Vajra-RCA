from app.pipeline import Pipeline


def test_attribution_helper_returns_features():
    p = Pipeline(); p.prepare(limit=4000)
    rows = p._replay_rows
    node = rows[rows["is_anomaly"] == 1]["dstip"].value_counts().index[0]
    res = p.shap_attribution(node)
    assert res["method"] in ("shap", "baseline_deviation")
    assert isinstance(res["features"], list) and len(res["features"]) >= 1
    assert {"feature", "contribution"} <= set(res["features"][0].keys())
