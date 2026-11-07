"""Tiered, deterministic resolver.

normalize -> exact -> length gate -> trigram top-K -> alias scores
-> max per entity -> threshold + margin -> MATCH | AMBIGUOUS | NOT_FOUND
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .config import ALGORITHM_VERSION, ResolverConfig
from .index import Indexes, build_indexes
from .kb import Entity, KnowledgeBase, load_kb
from .normalize import normalize
from .retrieval import retrieve
from .scoring import alias_score

# Scores are rounded so threshold/margin comparisons are not affected by
# float noise (e.g. 0.9 - 0.85 == 0.05000000000000004).
_SCORE_DIGITS = 6


class Status(str, Enum):
    MATCH = "MATCH"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_FOUND = "NOT_FOUND"


@dataclass(frozen=True)
class ResolveResult:
    input: str
    normalized_input: str
    status: Status
    canonical_id: str | None
    canonical_name: str | None
    # Similarity score in [0, 1] (1.0 for exact hits). NOT a probability.
    confidence: float | None
    match_type: str  # exact | fuzzy | none
    candidates: tuple[tuple[str, float], ...] = ()
    kb_version: str = ""
    algorithm_version: str = ALGORITHM_VERSION
    config_hash: str = ""

    def to_dict(self) -> dict:
        return {
            "input": self.input,
            "normalized_input": self.normalized_input,
            "status": self.status.value,
            "canonical_id": self.canonical_id,
            "canonical_name": self.canonical_name,
            "confidence": self.confidence,
            "match_type": self.match_type,
            "candidates": [{"id": cid, "score": score} for cid, score in self.candidates],
            "kb_version": self.kb_version,
            "algorithm_version": self.algorithm_version,
            "config_hash": self.config_hash,
        }


@dataclass
class Resolver:
    kb: KnowledgeBase
    config: ResolverConfig = field(default_factory=ResolverConfig)
    sink: object | None = None  # production.MetricsSink (use FanOutSink for several); optional

    def __post_init__(self) -> None:
        self.indexes: Indexes = build_indexes(self.kb)
        self._config_hash = self.config.config_hash()

    @classmethod
    def from_path(cls, path: str | Path | None = None, config: ResolverConfig | None = None, sink=None) -> "Resolver":
        """Build from a KB file; path=None uses the KB bundled with the package."""
        return cls(load_kb(path), config or ResolverConfig(), sink)

    # -- public API ---------------------------------------------------------

    def resolve(self, name: str) -> ResolveResult:
        start = time.perf_counter()
        result = self._resolve(name)
        if self.sink is not None:
            from .production import ResolutionEvent

            self.sink.record(ResolutionEvent.from_result(result, time.perf_counter() - start))
        return result

    def lookup_id(self, entity_id: str) -> Entity | None:
        """Map a stored canonical id - current or redirected (merged/renamed) - to its final entity.

        Returns None for ids the KB has never known. Use this for ids persisted
        by downstream systems before a merge; resolve() is for raw names.
        """
        return self.kb.lookup(entity_id)

    def retrieved_entity_ids(self, name: str) -> frozenset[str]:
        """Entity ids reachable from the top-K retrieval (used for Recall@K)."""
        q = normalize(name)
        aliases = retrieve(q, self.indexes, self.config.top_k)
        return frozenset(eid for alias in aliases for eid in self.indexes.exact_alias_index[alias])

    # -- pipeline -----------------------------------------------------------

    def _resolve(self, name: str) -> ResolveResult:
        q = normalize(name)
        if not q:
            return self._result(name, q, Status.NOT_FOUND, "none")

        ids = self.indexes.exact_alias_index.get(q)
        if ids:
            return self._from_id_set(name, q, ids, "exact")

        if len(q) < self.config.min_fuzzy_len:
            return self._result(name, q, Status.NOT_FOUND, "none")

        ranked = self._rank_entities(q)
        if not ranked or ranked[0][1] < self.config.threshold:
            return self._result(
                name, q, Status.NOT_FOUND, "none", candidates=ranked[: self.config.not_found_candidates]
            )

        best_score = ranked[0][1]
        # The threshold gates only the best entity; every entity within the
        # margin of it is a contender, even if it sits just below threshold.
        # Exact ties with the best are always contenders (even at margin 0),
        # so a tie can never become a MATCH.
        contenders = [
            (eid, s)
            for eid, s in ranked
            if s == best_score or round(best_score - s, _SCORE_DIGITS) < self.config.margin
        ]
        if len(contenders) == 1:
            eid = contenders[0][0]
            return self._result(name, q, Status.MATCH, "fuzzy", eid, best_score, candidates=contenders)
        return self._result(name, q, Status.AMBIGUOUS, "fuzzy", candidates=contenders)

    def _rank_entities(self, q: str) -> list[tuple[str, float]]:
        entity_scores: dict[str, float] = {}
        for alias in retrieve(q, self.indexes, self.config.top_k):
            score = round(alias_score(q, alias, self.config), _SCORE_DIGITS)
            for eid in self.indexes.exact_alias_index[alias]:
                # Max aggregation: an entity is as close as its closest alias.
                if score > entity_scores.get(eid, -1.0):
                    entity_scores[eid] = score
        # Tie-break by id only fixes output order; ties always fall within margin.
        return sorted(entity_scores.items(), key=lambda item: (-item[1], item[0]))

    def _from_id_set(self, name: str, q: str, ids: frozenset[str], match_type: str) -> ResolveResult:
        if len(ids) == 1:
            (eid,) = ids
            return self._result(name, q, Status.MATCH, match_type, eid, 1.0, candidates=[(eid, 1.0)])
        # Alias collision: stop here, never guess between the colliding entities.
        return self._result(name, q, Status.AMBIGUOUS, match_type, candidates=[(eid, 1.0) for eid in sorted(ids)])

    def _result(self, name, q, status, match_type, eid=None, confidence=None, candidates=()) -> ResolveResult:
        return ResolveResult(
            input=name,
            normalized_input=q,
            status=status,
            canonical_id=eid,
            canonical_name=self.kb.entities[eid].canonical_name if eid else None,
            confidence=confidence,
            match_type=match_type,
            candidates=tuple(candidates),
            kb_version=self.kb.version,
            config_hash=self._config_hash,
        )


_default: Resolver | None = None


def resolve(name: str) -> ResolveResult:
    """Resolve with the bundled KB and default config."""
    global _default
    if _default is None:
        _default = Resolver.from_path()
    return _default.resolve(name)


def lookup_id(entity_id: str) -> Entity | None:
    """lookup_id() with the bundled KB."""
    global _default
    if _default is None:
        _default = Resolver.from_path()
    return _default.lookup_id(entity_id)
