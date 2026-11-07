"""Alias-level similarity scoring.

score = w_jaccard * soft_token_jaccard + w_sequence * SequenceMatcher ratio

Scores are similarity values in [0, 1], not probabilities.
"""
from __future__ import annotations

from difflib import SequenceMatcher

from .config import ResolverConfig


def char_similarity(a: str, b: str) -> float:
    # autojunk=False keeps results independent of string length heuristics.
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def soft_token_jaccard(a: str, b: str, config: ResolverConfig) -> float:
    """Token Jaccard where near-identical tokens count as equal.

    Pairing is one-to-one: each token matches at most one token on the other
    side. Qualifying pairs are accepted greedily in (-similarity, i, j) order.
    Short-token policy: if either token has len <= short_token_len, the pair
    qualifies only on exact equality (so "eks" never pairs with "ecs").
    """
    left, right = a.split(), b.split()
    if not left or not right:
        return 0.0

    pairs: list[tuple[float, int, int]] = []
    for i, x in enumerate(left):
        for j, y in enumerate(right):
            if x == y:
                sim = 1.0
            elif len(x) <= config.short_token_len or len(y) <= config.short_token_len:
                continue
            else:
                sim = char_similarity(x, y)
                if sim < config.token_sim_threshold:
                    continue
            pairs.append((-sim, i, j))
    pairs.sort()

    used_left: set[int] = set()
    used_right: set[int] = set()
    for _, i, j in pairs:
        if i not in used_left and j not in used_right:
            used_left.add(i)
            used_right.add(j)

    matched = len(used_left)
    return matched / (len(left) + len(right) - matched)


def alias_score(query: str, alias: str, config: ResolverConfig) -> float:
    return (
        config.w_jaccard * soft_token_jaccard(query, alias, config)
        + config.w_sequence * char_similarity(query, alias)
    )
