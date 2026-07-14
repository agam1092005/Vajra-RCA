"""Vajra_SIH ML model bridge.

Loads the real trained models from Vajra_SIH/ml_models/ (*.pkl, *.joblib) via
MLModelManager and converts their threat predictions into our canonical Event type.

STACK DECISION:
- We do NOT import UnifiedLogger, kafka_bridge, or soar_engine from Vajra_SIH.
  Those belong to the old inline-firewall stack.  Our EventBus / FastAPI / Socket.IO
  is the new stack.
- We import only MLModelManager (pure sklearn / joblib — no conflicting deps).
- domain_classifier.h5 and gnn_fingerprint.tflite are skipped (require TensorFlow
  which breaks Python 3.12).

Usage:
    from .vajra_bridge import predict_flow
    events = predict_flow(row_attrs)   # list[Event], may be empty
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

from ..core.events import Event, EventType, Severity

# ---- locate Vajra_SIH relative to this file ----
# backend/app/ingestion/vajra_bridge.py -> repo root is [3] parents -> ../Vajra_SIH
_VAJRA_DIR = Path(__file__).resolve().parents[4] / "Vajra_SIH"
_MODELS_DIR = _VAJRA_DIR / "ml_models"

_manager = None
_load_attempted = False


def _get_manager():
    """Lazy-load MLModelManager from Vajra_SIH on first call."""
    global _manager, _load_attempted
    if _load_attempted:
        return _manager
    _load_attempted = True

    if not _VAJRA_DIR.exists():
        print(f"[VajraBridge] Vajra_SIH not found at {_VAJRA_DIR}. ML bridge disabled.")
        return None

    # Inject Vajra_SIH into sys.path so we can import its module directly
    vajra_str = str(_VAJRA_DIR)
    if vajra_str not in sys.path:
        sys.path.insert(0, vajra_str)

    try:
        # Import only MLModelManager — no Kafka/SOAR/UnifiedLogger
        from ml_model_manager import MLModelManager  # type: ignore
        mgr = MLModelManager(models_dir=str(_MODELS_DIR), log_file="/dev/null")

        # MLModelManager._log_prediction does json.dumps(asdict(prediction)); the
        # prediction's raw_input/features_used carry pandas-derived numpy int64
        # (e.g. src_port/dst_port), which json can't serialize -> it logs
        # "Failed to log prediction: Object of type int64 is not JSON serializable"
        # on every flow. That prediction log is the old inline-firewall stack's and
        # is already routed to /dev/null; we consume predictions via predict_all,
        # not the file. Disable it outright to stop the per-flow error spam.
        mgr._log_prediction = lambda *_a, **_k: None

        # Disable TF-dependent models that won't load in Python 3.12 venv
        _SKIP_MODELS = {"domain_classifier", "gnn_fingerprint"}
        for name in list(mgr.configs.keys()):
            if name in _SKIP_MODELS:
                mgr.configs[name].enabled = False
                print(f"[VajraBridge] Skipping TF-dependent model: {name}")

        loaded = [n for n, c in mgr.configs.items() if c.enabled]
        print(f"[VajraBridge] Loaded {len(loaded)} ML model(s): {loaded}")
        _manager = mgr
    except Exception as exc:
        print(f"[VajraBridge] Could not load MLModelManager: {exc}. Bridge disabled.")
        _manager = None
    return _manager


# map threat_type strings → our Severity
_SEVERITY_MAP: dict[str, Severity] = {
    "none":                         Severity.INFO,
    "network_anomaly":              Severity.MEDIUM,
    "ddos_attack":                  Severity.HIGH,
    "insider_threat":               Severity.HIGH,
    "suspicious_access_time":       Severity.MEDIUM,
    "suspicious_device_usage":      Severity.MEDIUM,
    "data_exfiltration_email":      Severity.HIGH,
    "data_exfiltration_http":       Severity.HIGH,
    "ml_detected_threat":           Severity.MEDIUM,
}


def predict_flow(row_attrs: dict[str, Any]) -> list[Event]:
    """Run all enabled Vajra ML models against one network flow's attributes.

    Returns a (possibly empty) list of SECURITY_ALERT Events for any model that
    flags `is_threat=True`.  Low-confidence predictions are still returned — they
    are real signal, just weighted accordingly by the RCA engine.
    """
    mgr = _get_manager()
    if mgr is None:
        return []

    try:
        preds = mgr.predict_all(row_attrs, data_type="network")
    except Exception as exc:
        print(f"[VajraBridge] predict_all failed: {exc}")
        return []

    events: list[Event] = []
    now = time.time()
    src = str(row_attrs.get("srcip") or row_attrs.get("src_ip") or "0.0.0.0")
    dst = str(row_attrs.get("dstip") or row_attrs.get("dst_ip") or "0.0.0.0")
    node = dst  # event is attributed to the target node

    for model_name, pred in preds.items():
        if not pred.is_threat:
            continue
        sev = _SEVERITY_MAP.get(pred.threat_type, Severity.MEDIUM)
        events.append(Event(
            event_type=EventType.SECURITY_ALERT,
            source=f"vajra_ml:{model_name}",
            node=node,
            timestamp=now,
            severity=sev,
            confidence=float(pred.confidence),
            signature=f"{pred.threat_type} detected by {model_name}",
            description=(
                f"ML model '{model_name}' flagged {src}->{dst} as "
                f"{pred.threat_type} (confidence={pred.confidence:.2f})"
            ),
            attributes={
                "model_name":    model_name,
                "threat_type":   pred.threat_type,
                "prediction":    pred.prediction,
                "confidence":    pred.confidence,
                "probabilities": pred.probabilities,
                "src_ip":        src,
                "dst_ip":        dst,
                "inference_ms":  pred.inference_time_ms,
            },
        ))
    return events
