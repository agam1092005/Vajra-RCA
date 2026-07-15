"""Feedback learning loop — pure-logic unit tests (no DB required)."""
from app.rca.scoring import (
    W_FEEDBACK_MAX,
    MAX_SCORE,
    feedback_boost_points,
    confidence_from_components,
    apply_feedback_boosts,
)
from app.db.store import aggregate_feedback_rows


# ---------- feedback_boost_points: capped, integer ----------

def test_boost_points_scales_with_net_votes():
    assert feedback_boost_points(1) == 5
    assert feedback_boost_points(2) == 10


def test_boost_points_capped_at_max_both_directions():
    assert feedback_boost_points(10) == W_FEEDBACK_MAX
    assert feedback_boost_points(-10) == -W_FEEDBACK_MAX


def test_boost_points_returns_int():
    result = feedback_boost_points(3)
    assert isinstance(result, int)


def test_boost_points_zero_net_is_zero():
    assert feedback_boost_points(0) == 0


# ---------- confidence_from_components: float in [0,1], floored ----------

def test_confidence_is_float_between_zero_and_one():
    c = confidence_from_components({"a": 30, "b": 30})
    assert isinstance(c, float)
    assert c == round(60 / MAX_SCORE, 3)


def test_confidence_floored_at_zero_for_negative_total():
    # A large negative feedback boost must not produce negative confidence.
    assert confidence_from_components({"a": 10, "feedback_learned_boost": -15}) >= 0.0
    assert confidence_from_components({"feedback_learned_boost": -15}) == 0.0


def test_confidence_capped_at_one():
    assert confidence_from_components({"a": 90, "b": 90}) == 1.0


# ---------- aggregate_feedback_rows: net vote map, flip-safe ----------

def _row(node, kind, is_correct):
    return {"focal_node": node, "hypothesis_kind": kind, "is_correct": is_correct}


def test_aggregate_counts_net_votes_by_node_and_kind():
    rows = [
        _row("10.0.0.1", "config_change", True),
        _row("10.0.0.1", "config_change", True),
        _row("10.0.0.1", "config_change", False),
    ]
    m = aggregate_feedback_rows(rows)
    assert m["node_kind"]["10.0.0.1|config_change"] == 1  # +1 +1 -1
    assert m["kind"]["config_change"] == 1


def test_aggregate_flip_is_single_row_no_double_count():
    # DB UNIQUE constraint means a flipped vote is ONE row; a correct vote nets +1.
    rows = [_row("n1", "attack", True)]
    m = aggregate_feedback_rows(rows)
    assert m["node_kind"]["n1|attack"] == 1
    assert m["kind"]["attack"] == 1


def test_aggregate_empty_rows():
    m = aggregate_feedback_rows([])
    assert m == {"node_kind": {}, "kind": {}}


# ---------- apply_feedback_boosts: re-rank so learning is visible ----------

def _hyp(rank, kind, components):
    total = min(MAX_SCORE, sum(components.values()))
    return {
        "rank": rank,
        "kind": kind,
        "root_cause": f"{kind} cause",
        "confidence": round(total / MAX_SCORE, 3),
        "score_breakdown": dict(components),
    }


def test_confirmed_correct_votes_promote_hypothesis_to_rank_one():
    # Rank-2 config_change is just behind rank-1 attack; 3 correct votes promote it.
    hyps = [
        _hyp(1, "attack", {"confirmed_attack_signatures": 40}),
        _hyp(2, "config_change", {"confirmed_config_change": 30}),
    ]
    boosts = {"node_kind": {"nodeA|config_change": 3}, "kind": {"config_change": 3}}
    out = apply_feedback_boosts(hyps, "nodeA", boosts)
    top = out[0]
    assert top["kind"] == "config_change"
    assert top["rank"] == 1
    assert top["score_breakdown"]["feedback_learned_boost"] == 15


def test_node_scope_preferred_over_global_fallback():
    hyps = [_hyp(1, "config_change", {"confirmed_config_change": 30})]
    boosts = {"node_kind": {"nodeA|config_change": 2}, "kind": {"config_change": -3}}
    out = apply_feedback_boosts(hyps, "nodeA", boosts)
    assert out[0]["score_breakdown"]["feedback_learned_boost"] == 10  # node-scoped +2*5


def test_global_fallback_when_no_node_specific_history():
    hyps = [_hyp(1, "config_change", {"confirmed_config_change": 30})]
    boosts = {"node_kind": {}, "kind": {"config_change": 1}}
    out = apply_feedback_boosts(hyps, "nodeB", boosts)
    assert out[0]["score_breakdown"]["feedback_learned_boost"] == 5


def test_no_feedback_leaves_hypotheses_unchanged():
    hyps = [_hyp(1, "attack", {"confirmed_attack_signatures": 40})]
    out = apply_feedback_boosts(hyps, "nodeA", {"node_kind": {}, "kind": {}})
    assert "feedback_learned_boost" not in out[0]["score_breakdown"]
    assert out[0]["rank"] == 1
