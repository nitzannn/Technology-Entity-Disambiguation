"""Resolver configuration and version identifiers.

Determinism contract: the same (kb_version, ALGORITHM_VERSION, config_hash)
always yields the same output for the same input.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

# Bump whenever normalization, retrieval, scoring or decision logic changes.
ALGORITHM_VERSION = "1.1.0"  # 1.1.0: bounded top-K retrieval with Jaccard tie-break


@dataclass(frozen=True)
class ResolverConfig:
    # Minimum entity score for a fuzzy result to be considered at all.
    # Tuned with margin on the dev split by F0.5 (see docs/DESIGN.md); 0.75 leaves
    # ~0.03 clearance above the highest-scoring dev negative
    # ("Microsoft Defender for Identity", 0.719).
    threshold: float = 0.75
    # Entities within `margin` of the best score are contenders; >1 contender -> AMBIGUOUS.
    margin: float = 0.10
    # Hard upper bound on distinct alias strings retrieved for scoring (strict cut, see retrieval.py).
    top_k: int = 25
    # alias score = w_jaccard * soft_token_jaccard + w_sequence * SequenceMatcher ratio
    w_jaccard: float = 0.5
    w_sequence: float = 0.5
    # Two tokens may pair in soft Jaccard if their character similarity >= this.
    token_sim_threshold: float = 0.8
    # Tokens of this length or shorter only pair on exact equality ("eks" != "ecs").
    short_token_len: int = 3
    # Normalized inputs shorter than this skip fuzzy matching entirely.
    min_fuzzy_len: int = 4
    # Number of near-miss candidates attached to NOT_FOUND results for review.
    not_found_candidates: int = 3

    def __post_init__(self) -> None:
        def require(ok: bool, message: str) -> None:
            if not ok:
                raise ValueError(f"invalid ResolverConfig: {message}")

        for name in ("threshold", "margin", "token_sim_threshold", "w_jaccard", "w_sequence"):
            value = getattr(self, name)
            require(isinstance(value, (int, float)) and not isinstance(value, bool), f"{name} must be a number")
            require(0.0 <= value <= 1.0, f"{name}={value} must be within [0, 1]")
        # Weights must sum to 1 so alias scores stay within [0, 1].
        require(abs(self.w_jaccard + self.w_sequence - 1.0) < 1e-9,
                f"w_jaccard + w_sequence must equal 1 (got {self.w_jaccard + self.w_sequence})")
        for name, minimum in (("top_k", 1), ("short_token_len", 0), ("min_fuzzy_len", 0), ("not_found_candidates", 0)):
            value = getattr(self, name)
            require(isinstance(value, int) and not isinstance(value, bool), f"{name} must be an integer")
            require(value >= minimum, f"{name}={value} must be >= {minimum}")

    def config_hash(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True).encode()
        return hashlib.sha256(payload).hexdigest()[:12]
