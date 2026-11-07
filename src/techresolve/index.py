"""Indexes derived from the KB at load time (never persisted as truth).

- exact_alias_index: normalize(alias) -> frozenset of final entity ids
- trigram_index:     trigram          -> sorted tuple of distinct normalized alias strings

Alias collisions are kept as multi-id sets; the resolver turns them into
AMBIGUOUS results. All ids pass through KnowledgeBase.final_id() before
insertion, so ids that redirect to the same target count as one entity.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .kb import KnowledgeBase
from .normalize import normalize


def trigrams(normalized: str) -> frozenset[str]:
    padded = f"  {normalized} "
    return frozenset(padded[i : i + 3] for i in range(len(padded) - 2))


@dataclass(frozen=True)
class Indexes:
    exact_alias_index: dict[str, frozenset[str]]
    trigram_index: dict[str, tuple[str, ...]]
    alias_trigrams: dict[str, frozenset[str]]  # normalized alias -> its trigrams


def build_indexes(kb: KnowledgeBase) -> Indexes:
    exact: dict[str, set[str]] = defaultdict(set)

    for entity in kb.entities.values():
        target = kb.final_id(entity.id)
        for alias in entity.aliases:
            exact[normalize(alias)].add(target)

    postings: dict[str, set[str]] = defaultdict(set)
    alias_trigrams: dict[str, frozenset[str]] = {}
    for alias in exact:
        grams = trigrams(alias)
        alias_trigrams[alias] = grams
        for gram in grams:
            postings[gram].add(alias)

    return Indexes(
        exact_alias_index={k: frozenset(v) for k, v in exact.items()},
        trigram_index={k: tuple(sorted(v)) for k, v in postings.items()},
        alias_trigrams=alias_trigrams,
    )
