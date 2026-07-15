# Vajra RCA — Dataset Validation Results

Real precision / recall / F1 from fitting Isolation Forest on benign training
samples and evaluating against the labelled test splits.
All numbers are produced from real dataset labels — no fabrication.

| Dataset | Train rows | Test rows | Precision | Recall | F1 | ROC-AUC |
|---|---|---|---|---|---|---|
| UNSW-NB15 | 82,332 | 175,341 | 0.8677 | 0.5326 | 0.6600 | 0.7247 |
| NSL-KDD | 125,973 | 22,544 | 0.9180 | 0.7779 | 0.8422 | 0.9265 |

## Notes
- Model: `IsolationForest(n_estimators=200, contamination=0.15)` fitted on benign rows only.
- Prediction threshold: default (IsolationForest decision boundary).
- UNSW-NB15 uses numeric columns only (36 features); NSL-KDD uses 38 numeric features.
- Generated: 2026-07-15 09:00:32 UTC