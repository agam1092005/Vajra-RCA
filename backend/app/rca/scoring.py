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
W_EXPLAINED_SIGNATURE = 30     # a named behavioral signature (MITRE-mapped) matched the anomaly
W_FEATURE_ATTRIBUTION = 15     # specific deviating features named from the detector
MAX_SCORE = 100

# --- Feedback learning loop (operator marks a hypothesis Correct/Wrong) ---
W_FEEDBACK_STEP = 5            # score points awarded per net correct-vs-wrong vote
W_FEEDBACK_MAX = 15           # hard cap: feedback only NUDGES ranking, never overturns
                              # strong confirmed evidence (max ±15 of MAX_SCORE=100).


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
        # Floor at 0 so a negative component (e.g. a "wrong RCA" feedback boost)
        # can never yield a negative total / confidence.
        return max(0, min(MAX_SCORE, sum(self.components.values())))

    @property
    def confidence(self) -> float:
        return round(self.total / MAX_SCORE, 3)


def feedback_boost_points(net_votes: int) -> int:
    """Convert net operator votes (correct=+1, wrong=-1) into capped score points.

    Deterministic and CAPPED at ±W_FEEDBACK_MAX so learned feedback only nudges
    ranking — it can never overturn a hypothesis backed by strong confirmed evidence.
    Returns a clean int (drives the `feedback_learned_boost` breakdown pill).
    """
    points = net_votes * W_FEEDBACK_STEP
    return max(-W_FEEDBACK_MAX, min(W_FEEDBACK_MAX, points))


def confidence_from_components(components: dict[str, int]) -> float:
    """Recompute a hypothesis' 0-1 confidence from its (possibly boosted) score
    components. Total is floored at 0 and capped at MAX_SCORE; confidence is the
    float ratio the UI's ConfidenceBar consumes."""
    total = max(0, min(MAX_SCORE, sum(components.values())))
    return round(total / MAX_SCORE, 3)


def apply_feedback_boosts(hypotheses: list[dict], focal_node: str,
                          boosts: dict) -> list[dict]:
    """Apply the learned feedback boost to each hypothesis, then RE-SORT and
    RE-RANK so a promoted hypothesis visibly becomes the new #1.

    `boosts` is the map from `store.feedback_boost_map()`:
        {"node_kind": {"<node>|<kind>": net}, "kind": {"<kind>": net}}
    Node-scoped feedback wins; global per-kind feedback is the fallback.
    Mutates and returns the same list of hypothesis dicts.
    """
    node_kind = boosts.get("node_kind", {})
    by_kind = boosts.get("kind", {})
    for h in hypotheses:
        kind = h.get("kind", "")
        key = f"{focal_node}|{kind}"
        net = node_kind[key] if key in node_kind else by_kind.get(kind, 0)
        points = feedback_boost_points(net)
        if points:
            h["score_breakdown"]["feedback_learned_boost"] = points
            h["confidence"] = confidence_from_components(h["score_breakdown"])
    hypotheses.sort(key=lambda h: h.get("confidence", 0.0), reverse=True)
    for i, h in enumerate(hypotheses, 1):
        h["rank"] = i
    return hypotheses


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
    warning: str = ""
