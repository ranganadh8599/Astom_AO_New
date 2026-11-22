"""Reciprocal rank fusion: merging one ranked list per question into a single shortlist."""

from __future__ import annotations

from orchestrator.gateway import Target
from orchestrator.routing.rank_fusion import reciprocal_rank_fusion


def _t(name: str, score: float = 0.0) -> Target:
    return Target(agent_id=name, agent_name=name, search_score=score)


def _names(targets: list[Target]) -> list[str]:
    return [t.agent_id for t in targets]


def test_single_ranking_is_returned_unchanged() -> None:
    ranking = [_t("b"), _t("a"), _t("c")]
    assert _names(reciprocal_rank_fusion([ranking])) == ["b", "a", "c"]


def test_no_rankings_is_empty() -> None:
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[], []]) == []


def test_each_questions_best_target_survives_the_merge() -> None:
    """The point of splitting: neither topic can push the other out of the shortlist."""
    hr = [_t("hr-1"), _t("hr-2"), _t("hr-3")]
    finance = [_t("fin-1"), _t("fin-2"), _t("fin-3")]

    fused = _names(reciprocal_rank_fusion([hr, finance], limit=2))

    assert set(fused) == {"hr-1", "fin-1"}


def test_a_target_ranked_by_several_questions_wins() -> None:
    first = [_t("x"), _t("shared")]
    second = [_t("y"), _t("shared")]

    assert _names(reciprocal_rank_fusion([first, second]))[0] == "shared"


def test_duplicates_collapse_and_keep_the_higher_score() -> None:
    fused = reciprocal_rank_fusion([[_t("a", 0.2)], [_t("a", 0.7)]])

    assert len(fused) == 1 and fused[0].search_score == 0.7


def test_ties_keep_first_seen_order() -> None:
    fused = reciprocal_rank_fusion([[_t("a")], [_t("b")]])

    assert _names(fused) == ["a", "b"]
