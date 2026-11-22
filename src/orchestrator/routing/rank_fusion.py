"""Merging several ranked lists into one.

A message with more than one question is searched once per question, which gives one
ranked list per question. Reciprocal rank fusion merges them without needing the scores to
be comparable (they are not: each is relative to its own query):

    score(target) = sum over lists of 1 / (k + rank)

A target near the top of any list scores well, and one that appears in several lists
scores best. ``k`` damps the advantage of rank 1 over rank 2; 60 is the value from the
original paper and is not worth tuning here.
"""

from __future__ import annotations

from collections.abc import Sequence

from orchestrator.gateway import Target

RRF_K = 60


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[Target]],
    *,
    limit: int | None = None,
    k: int = RRF_K,
) -> list[Target]:
    """One list, best first, each target once (identified by ``agent_id``).

    A single ranking is returned unchanged, so the common case costs nothing and keeps the
    gateway's own order. For a target seen in several lists the copy with the highest
    ``search_score`` is kept, because that is the most informative one for the gate.
    """
    non_empty = [list(r) for r in rankings if r]
    if not non_empty:
        return []
    if len(non_empty) == 1:
        fused = non_empty[0]
        return fused[:limit] if limit and limit > 0 else fused

    scores: dict[str, float] = {}
    best: dict[str, Target] = {}
    first_seen: dict[str, int] = {}
    for ranking in non_empty:
        for rank, target in enumerate(ranking):
            key = target.agent_id
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            first_seen.setdefault(key, len(first_seen))
            kept = best.get(key)
            if kept is None or target.search_score > kept.search_score:
                best[key] = target

    ordered = sorted(scores, key=lambda key: (-scores[key], first_seen[key]))
    fused = [best[key] for key in ordered]
    return fused[:limit] if limit and limit > 0 else fused
