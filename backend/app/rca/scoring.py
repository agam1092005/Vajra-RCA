"""Deterministic, decomposable causal scoring + evidence taxonomy.

The score is intentionally transparent (each component is named and additive) so
the UI can show *why* a hypothesis ranks where it does — the spec's requirement to
"avoid presenting an uncertain hypothesis as an absolute conclusion" and to keep
the confidence "explainable and decomposable".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# --- Scoring weights (from the Architecture doc's "Statistical and Temporal Scoring") ---
W_CONFIG_WITHIN_WINDOW = 30    # a config change on/upstream of the node just before the anomaly
W_DIRECT_UPSTREAM_DEP = 30     # a real dependency path supports propagation
W_CONFIRMED_MATCH = 30         # confirmed direct evidence (signature/label/diff directly matches)
W_MATCHING_PROPAGATION = 20    # anomaly on upstream temporally precedes the downstream anomaly
W_HISTORICAL_MATCH = 10        # a similar past incident exists (RAG/history)
W_INDEPENDENT_SIGNAL = 10      # an independent corroborating signal (alert/error log)
MAX_SCORE = 100


class EvidenceKind(str, Enum):
    CONFIRMED = "confirmed"     # direct, verifiable proof
    CORRELATED = "correlated"   # same-window, not proven causal
    MISSING = "missing"         # would confirm/reject but unavailable


@dataclass
class EvidenceItem:
    kind: EvidenceKind
    text: str
    source: str = ""
    weight_component: str = ""   # which score component this backs, if any


@dataclass
class ScoreBreakdown:
    components: dict[str, int] = field(default_factory=dict)

    def add(self, name: str, points: int) -> None:
        if points:
            self.components[name] = self.components.get(name, 0) + points

    @property
    def total(self) -> int:
        return min(MAX_SCORE, sum(self.components.values()))

    @property
    def confidence(self) -> float:
        return round(self.total / MAX_SCORE, 3)


# Risk tiers for recommendations (spec: distinguish diagnostic / low-risk / high-impact).
class RiskTier(str, Enum):
    DIAGNOSTIC = "diagnostic"
    LOW_RISK = "low_risk"
    HIGH_IMPACT = "high_impact"


@dataclass
class Recommendation:
    action: str
    tier: RiskTier
    reason: str
    requires_human_approval: bool = False
