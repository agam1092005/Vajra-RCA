"""Kitsune online network anomaly detector.

Ported from Vajra_SIH/kitsune_engine.py.
Algorithm: Mirsky et al. "Kitsune: An Ensemble of Autoencoders for Online Network Intrusion Detection" (NDSS 2018).

Changes from original:
- Removed all file logging / logs/ directory creation
- Removed standalone __main__ block
- Removed FastAPI / WebSocket dependency
- Removed Kafka / UnifiedEvent references
- Returns our own domain objects (no KitsuneAnomaly dataclass from Vajra)
- Thread-safe singleton via get_kitsune_engine()
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Optional

try:
    import numpy as np
    _NUMPY = True
except ImportError:
    _NUMPY = False
    np = None  # type: ignore


# ---------------------------------------------------------------------------
# AfterImage — incremental flow statistics
# ---------------------------------------------------------------------------

class _AfterImage:
    """Incremental per-host statistics tracker (online feature extraction)."""

    def __init__(self, max_host_limit: int = 255):
        self.max_host_limit = max_host_limit
        self.host_stats: dict[str, dict] = defaultdict(lambda: {
            "count": 0, "total_bytes": 0, "total_packets": 0,
            "protocols": set(), "ports": set(), "last_timestamp": 0.0,
        })

    def update(self, packet: dict[str, Any]) -> list[float]:
        src = packet.get("src_ip", "0.0.0.0")
        protocol = packet.get("protocol", "TCP")
        dst_port = int(packet.get("dst_port") or 0)
        length = float(packet.get("packet_length") or 0)
        ts = float(packet.get("timestamp") or time.time())

        h = self.host_stats[src]
        h["count"] += 1
        h["total_bytes"] += length
        h["total_packets"] += 1
        h["protocols"].add(protocol)
        h["ports"].add(dst_port)
        delta = ts - h["last_timestamp"] if h["last_timestamp"] > 0 else 0.0
        h["last_timestamp"] = ts

        features = [
            float(h["count"]),
            float(h["total_bytes"]),
            float(h["total_bytes"]) / max(h["count"], 1),
            delta,
            1.0 / max(delta, 1e-3),
            float(len(h["protocols"])),
            float(len(h["ports"])),
            length,
            float(dst_port),
        ]
        if len(self.host_stats) > self.max_host_limit:
            self._evict()
        return features

    def _evict(self) -> None:
        oldest = sorted(self.host_stats, key=lambda k: self.host_stats[k]["last_timestamp"])
        for k in oldest[: len(oldest) // 5]:
            del self.host_stats[k]


# ---------------------------------------------------------------------------
# Autoencoder — single incremental autoencoder unit
# ---------------------------------------------------------------------------

class _Autoencoder:
    def __init__(self, input_size: int, lr: float = 0.1):
        assert _NUMPY, "NumPy required for Kitsune"
        hs = max(input_size // 2, 1)
        self.W1 = np.random.randn(input_size, hs) * 0.1
        self.b1 = np.zeros(hs)
        self.W2 = np.random.randn(hs, input_size) * 0.1
        self.b2 = np.zeros(input_size)
        self.lr = lr
        self._n = 0
        self._mean_err = 0.0
        self._std_err = 1.0

    def _forward(self, x: "np.ndarray"):
        h = np.tanh(x @ self.W1 + self.b1)
        return np.tanh(h @ self.W2 + self.b2), h

    def train(self, x: "np.ndarray") -> float:
        out, h = self._forward(x)
        err = x - out
        loss = float(np.mean(err ** 2))
        # backprop
        d2 = err * (1 - out ** 2)
        d1 = (d2 @ self.W2.T) * (1 - h ** 2)
        self.W2 += self.lr * np.outer(h, d2)
        self.b2 += self.lr * d2
        self.W1 += self.lr * np.outer(x, d1)
        self.b1 += self.lr * d1
        self._n += 1
        self._mean_err += (loss - self._mean_err) / self._n
        self._std_err = max(self._std_err, abs(loss - self._mean_err))
        return loss

    def score(self, x: "np.ndarray") -> float:
        out, _ = self._forward(x)
        return float(np.mean((x - out) ** 2))

    @property
    def threshold(self) -> float:
        return self._mean_err + 3 * self._std_err


# ---------------------------------------------------------------------------
# KitNET — ensemble of autoencoders
# ---------------------------------------------------------------------------

class _KitNET:
    def __init__(self, feature_size: int, ensemble_size: int = 10, lr: float = 0.1):
        assert _NUMPY, "NumPy required for Kitsune"
        self.ensemble_size = ensemble_size
        chunk = max(feature_size // ensemble_size, 1)
        # Random feature partition into sub-groups
        idx = np.random.permutation(feature_size)
        self._groups = [idx[i * chunk: (i + 1) * chunk].tolist()
                        for i in range(ensemble_size)]
        # Pad last group with leftovers
        used = ensemble_size * chunk
        if used < feature_size:
            self._groups[-1].extend(range(used, feature_size))
        self._aes = [_Autoencoder(len(g), lr) for g in self._groups]
        # Output-layer AE merges per-AE scores
        self._out_ae = _Autoencoder(ensemble_size, lr)

    def process(self, x: "np.ndarray", train: bool) -> float:
        sub_scores = np.array([
            ae.train(x[g]) if train else ae.score(x[g])
            for ae, g in zip(self._aes, self._groups)
        ], dtype=np.float32)
        if train:
            self._out_ae.train(sub_scores)
            return 0.0
        return self._out_ae.score(sub_scores)


# ---------------------------------------------------------------------------
# KitsuneEngine — public API
# ---------------------------------------------------------------------------

@dataclass
class KitsuneResult:
    src_ip: str
    dst_ip: str
    anomaly_score: float
    is_anomaly: bool
    reconstruction_error: float


class KitsuneEngine:
    """Online anomaly detector for network flows. Thread-safe."""

    def __init__(
        self,
        ensemble_size: int = 10,
        grace_period: int = 1000,
        anomaly_threshold: float = 0.1,
        learning_rate: float = 0.1,
    ):
        self.enabled = _NUMPY
        self.ensemble_size = ensemble_size
        self.grace_period = grace_period
        self.anomaly_threshold = anomaly_threshold
        self.learning_rate = learning_rate

        self._lock = threading.Lock()
        self._afterimage = _AfterImage()
        self._kitnet: "_KitNET | None" = None
        self.packet_count = 0
        self.anomaly_count = 0
        self.training_mode = True

    @property
    def warmed_up(self) -> bool:
        return self.packet_count >= self.grace_period

    def process_packet(self, packet: dict[str, Any]) -> Optional[KitsuneResult]:
        """Feed one flow/packet dict; returns KitsuneResult if anomalous (post-warmup), else None."""
        if not self.enabled:
            return None
        with self._lock:
            try:
                features = self._afterimage.update(packet)
                fv = np.array(features, dtype=np.float32)
                fv = np.nan_to_num(fv, nan=0.0, posinf=1e6, neginf=-1e6)

                if self._kitnet is None:
                    self._kitnet = _KitNET(
                        len(fv), self.ensemble_size, self.learning_rate
                    )

                self.packet_count += 1

                # Grace (training) period — build baseline
                if self.packet_count <= self.grace_period:
                    self._kitnet.process(fv, train=True)
                    if self.packet_count == self.grace_period:
                        self.training_mode = False
                    return None

                score = self._kitnet.process(fv, train=False)
                is_anomaly = score > self.anomaly_threshold

                if is_anomaly:
                    self.anomaly_count += 1
                    return KitsuneResult(
                        src_ip=packet.get("src_ip", "0.0.0.0"),
                        dst_ip=packet.get("dst_ip", "0.0.0.0"),
                        anomaly_score=float(score),
                        is_anomaly=True,
                        reconstruction_error=float(score),
                    )
                return None
            except Exception:
                return None

    def stats(self) -> dict:
        return {
            "enabled": self.enabled,
            "packet_count": self.packet_count,
            "anomaly_count": self.anomaly_count,
            "training_mode": self.training_mode,
            "warmed_up": self.warmed_up,
            "grace_period": self.grace_period,
            "anomaly_threshold": self.anomaly_threshold,
        }

    def reset(self) -> None:
        with self._lock:
            self._kitnet = None
            self._afterimage = _AfterImage()
            self.packet_count = 0
            self.anomaly_count = 0
            self.training_mode = True


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[KitsuneEngine] = None
_instance_lock = threading.Lock()


def get_kitsune_engine() -> KitsuneEngine:
    """Return the process-level KitsuneEngine singleton."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = KitsuneEngine()
        return _instance
