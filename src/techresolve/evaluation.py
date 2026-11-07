"""Offline evaluation against a hand-labeled gold set.

Scoring rules:
  - expected MATCH X     -> correct iff status MATCH and canonical_id == X
  - expected AMBIGUOUS S -> correct iff status AMBIGUOUS and candidate ids ⊇ S
  - expected NOT_FOUND   -> correct iff status NOT_FOUND
  TP = correct MATCH; FP = any MATCH that is not correct;
  FN = expected MATCH whose result is not a correct MATCH
  (a wrong-id MATCH therefore counts as both FP and FN).

FP is the costliest business error and the headline metric: any MATCH that is
not correct, whatever the expected status (wrong id, a MATCH on a NOT_FOUND
row, or a MATCH on an AMBIGUOUS row).
The regression diff flags every row that *newly* becomes an FP, even when it
was already incorrect before (e.g. NOT_FOUND -> wrong MATCH).

Generalization: each row is also tagged "seen" if its normalized form is
already a key of the exact alias index (lookup alone can solve it),
otherwise "novel". Metrics are reported for both, so a score dominated by
verbatim KB aliases is visible as such.

Regression rows are re-scored against the *current* gold set, so a reviewed
gold-label change shipped in the same PR as a KB change is judged correctly.
"""
from __future__ import annotations

import csv
import statistics
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from .config import ALGORITHM_VERSION
from .normalize import normalize
from .resolver import Resolver, ResolveResult, Status

@dataclass(frozen=True)
class GoldRow:
    input: str
    expected_status: Status
    expected_ids: frozenset[str]
    category: str
    split: str
    note: str = ""


@dataclass(frozen=True)
class Outcome:
    """The part of a result that evaluation and regression diffs care about."""

    status: str
    canonical_id: str | None
    candidate_ids: tuple[str, ...]

    @classmethod
    def from_result(cls, result: ResolveResult) -> "Outcome":
        return cls(result.status.value, result.canonical_id, tuple(cid for cid, _ in result.candidates))

    def to_dict(self) -> dict:
        return {"status": self.status, "canonical_id": self.canonical_id, "candidate_ids": list(self.candidate_ids)}

    @classmethod
    def from_dict(cls, data: dict) -> "Outcome":
        return cls(data["status"], data["canonical_id"], tuple(data["candidate_ids"]))


def load_gold(path: str | Path, split: str = "all") -> list[GoldRow]:
    rows: list[GoldRow] = []
    seen: set[str] = set()
    with open(path, newline="", encoding="utf-8") as handle:
        for record in csv.DictReader(handle):
            if record["input"] in seen:
                raise ValueError(f"duplicate gold input: {record['input']!r}")
            seen.add(record["input"])
            if split != "all" and record["split"] != split:
                continue
            ids = frozenset(i for i in record["expected_ids"].split(";") if i)
            rows.append(GoldRow(record["input"], Status(record["expected_status"]), ids,
                                record["category"], record["split"], record.get("note") or ""))
    return rows


def is_correct(row: GoldRow, outcome: Outcome) -> bool:
    if row.expected_status is Status.MATCH:
        return outcome.status == Status.MATCH.value and outcome.canonical_id in row.expected_ids
    if row.expected_status is Status.AMBIGUOUS:
        return outcome.status == Status.AMBIGUOUS.value and row.expected_ids <= set(outcome.candidate_ids)
    return outcome.status == Status.NOT_FOUND.value


def classify(row: GoldRow, outcome: Outcome) -> tuple[bool, bool, bool]:
    """Return (tp, fp, fn) for one row."""
    correct = is_correct(row, outcome)
    is_match = outcome.status == Status.MATCH.value
    tp = is_match and correct
    fp = is_match and not correct
    fn = row.expected_status is Status.MATCH and not (is_match and correct)
    return tp, fp, fn


def is_seen(resolver: Resolver, text: str) -> bool:
    """True if exact lookup alone covers this surface form."""
    return normalize(text) in resolver.indexes.exact_alias_index


def _subset_metrics(pairs: list[tuple[GoldRow, Outcome]]) -> dict:
    tp = fp = fn = correct = 0
    for row, outcome in pairs:
        t, f, n = classify(row, outcome)
        tp, fp, fn, correct = tp + t, fp + f, fn + n, correct + is_correct(row, outcome)
    return {
        "rows": len(pairs),
        "accuracy": correct / len(pairs) if pairs else None,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "fp": fp,
        "fn": fn,
    }


def evaluate(resolver: Resolver, rows: list[GoldRow], timing_repeats: int = 0) -> dict:
    outcomes: dict[str, Outcome] = {}
    tp = fp = fn = 0
    errors: list[dict] = []
    per_category: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    status_counts: Counter[str] = Counter()
    fuzzy_total = fuzzy_hit = amb_total = amb_hit = 0
    by_surface: dict[str, list[tuple[GoldRow, Outcome]]] = {"seen": [], "novel": []}
    fp_by_expected: Counter[str] = Counter()

    for row in rows:
        result = resolver.resolve(row.input)
        outcome = Outcome.from_result(result)
        outcomes[row.input] = outcome
        status_counts[outcome.status] += 1
        by_surface["seen" if is_seen(resolver, row.input) else "novel"].append((row, outcome))

        t, f, n = classify(row, outcome)
        tp, fp, fn = tp + t, fp + f, fn + n
        if f:
            fp_by_expected[row.expected_status.value] += 1
        correct = is_correct(row, outcome)
        per_category[row.category][0] += correct
        per_category[row.category][1] += 1
        if not correct:
            errors.append({"input": row.input, "category": row.category,
                           "expected": f"{row.expected_status.value} {sorted(row.expected_ids)}",
                           "got": f"{outcome.status} {outcome.canonical_id or list(outcome.candidate_ids)}",
                           "fp": f, "fn": n})

        # Candidate Recall@K, only for inputs that actually reach retrieval.
        reached_fuzzy = result.match_type in ("fuzzy", "none") and len(result.normalized_input) >= resolver.config.min_fuzzy_len
        if reached_fuzzy and row.expected_ids:
            retrieved = resolver.retrieved_entity_ids(row.input)
            hit = row.expected_ids <= retrieved
            if row.expected_status is Status.AMBIGUOUS:
                amb_total, amb_hit = amb_total + 1, amb_hit + hit
            else:
                fuzzy_total, fuzzy_hit = fuzzy_total + 1, fuzzy_hit + hit

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f05 = 1.25 * precision * recall / (0.25 * precision + recall) if precision + recall else 0.0
    n_rows = len(rows) or 1

    report = {
        "rows": len(rows),
        "kb_version": resolver.kb.version,
        "algorithm_version": ALGORITHM_VERSION,
        "config_hash": resolver.config.config_hash(),
        "config": resolver.config,
        "precision": precision, "recall": recall, "f05": f05,
        "accuracy": sum(c for c, _ in per_category.values()) / n_rows,
        "tp": tp, "fp": fp, "fn": fn,
        "fp_by_expected": dict(sorted(fp_by_expected.items())),
        "ambiguous_rate": status_counts[Status.AMBIGUOUS.value] / n_rows,
        "not_found_rate": status_counts[Status.NOT_FOUND.value] / n_rows,
        "recall_at_k": (fuzzy_hit / fuzzy_total) if fuzzy_total else None,
        "recall_at_k_n": fuzzy_total,
        "ambiguous_recall_at_k": (amb_hit / amb_total) if amb_total else None,
        "ambiguous_recall_at_k_n": amb_total,
        "per_category": {k: tuple(v) for k, v in sorted(per_category.items())},
        "by_surface": {k: _subset_metrics(v) for k, v in by_surface.items()},
        "errors": errors,
        "outcomes": outcomes,
    }
    if timing_repeats:
        report["latency"] = measure_latency(resolver, [r.input for r in rows], timing_repeats)
    return report


def measure_latency(resolver: Resolver, inputs: list[str], repeats: int) -> dict:
    samples: list[float] = []
    for _ in range(repeats):
        for text in inputs:
            start = time.perf_counter()
            resolver.resolve(text)
            samples.append(time.perf_counter() - start)
    samples.sort()
    pick = lambda p: samples[min(len(samples) - 1, int(p * len(samples)))] * 1e3
    return {"p50_ms": pick(0.50), "p95_ms": pick(0.95), "p99_ms": pick(0.99),
            "mean_ms": statistics.fmean(samples) * 1e3, "calls": len(samples)}


def diff_against_baseline(rows: list[GoldRow], baseline: dict[str, Outcome], current: dict[str, Outcome]) -> dict:
    """Classify every changed row as improvement / regression / neutral."""
    changes: dict[str, list[dict]] = {"improvement": [], "regression": [], "neutral": []}
    new_ambiguous: list[str] = []
    new_fp: list[str] = []
    new_rows: list[str] = []
    for row in rows:
        after = current[row.input]
        before = baseline.get(row.input)
        if before is None:
            new_rows.append(row.input)
            continue
        if before == after:
            continue
        was, now = is_correct(row, before), is_correct(row, after)
        kind = "improvement" if (not was and now) else "regression" if (was and not now) else "neutral"
        changes[kind].append({"input": row.input, "before": before.to_dict(), "after": after.to_dict()})
        if classify(row, after)[1] and not classify(row, before)[1]:
            new_fp.append(row.input)
        if after.status == Status.AMBIGUOUS.value and before.status != Status.AMBIGUOUS.value:
            new_ambiguous.append(row.input)
    return {**changes, "new_ambiguous": new_ambiguous, "new_fp": new_fp, "new_rows": new_rows}
