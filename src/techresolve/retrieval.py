"""Candidate retrieval via the trigram inverted index.

Retrieval only narrows the search space; it never decides a match. Its unit
is the distinct normalized alias string, so an alias shared by several
entities is retrieved (or dropped) as a whole and its entities can never be
split across the top-K cutoff.
"""
from __future__ import annotations

from collections import Counter

from .index import Indexes, trigrams


def retrieve(query: str, indexes: Indexes, top_k: int) -> list[str]:
    """Return at most `top_k` candidate alias strings.

    Ranking (fully deterministic, strict cut at K):
      1. shared-trigram count, descending
      2. trigram Jaccard (shared / union), descending - among equal overlap,
         prefer aliases whose length is closer to the query
      3. alias string, ascending - final, arbitrary but stable tie-break
    """
    query_grams = trigrams(query)
    shared: Counter[str] = Counter()
    for gram in query_grams:
        for alias in indexes.trigram_index.get(gram, ()):
            shared[alias] += 1

    def rank_key(item: tuple[str, int]) -> tuple[int, float, str]:
        alias, count = item
        union = len(query_grams) + len(indexes.alias_trigrams[alias]) - count
        return (-count, -count / union, alias)

    ranked = sorted(shared.items(), key=rank_key)
    return [alias for alias, _ in ranked[:top_k]]
