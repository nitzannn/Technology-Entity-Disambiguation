"""Production concerns: lightweight interfaces and stubs only.

Nothing here affects resolution. The resolver emits a ResolutionEvent per
call to an optional MetricsSink; the in-memory implementations below show
what would be aggregated. Production equivalents are described inline.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Protocol

from .resolver import ResolveResult, Status


@dataclass(frozen=True)
class ResolutionEvent:
    input: str
    normalized_input: str
    status: str
    canonical_id: str | None
    score: float | None
    candidates: tuple[tuple[str, float], ...]
    kb_version: str
    algorithm_version: str
    config_hash: str
    latency_s: float

    @classmethod
    def from_result(cls, result: ResolveResult, latency_s: float) -> "ResolutionEvent":
        return cls(
            input=result.input,
            normalized_input=result.normalized_input,
            status=result.status.value,
            canonical_id=result.canonical_id,
            score=result.confidence,
            candidates=result.candidates,
            kb_version=result.kb_version,
            algorithm_version=result.algorithm_version,
            config_hash=result.config_hash,
            latency_s=latency_s,
        )


class MetricsSink(Protocol):
    def record(self, event: ResolutionEvent) -> None: ...


class FanOutSink:
    """Forwards each event to several sinks (e.g. metrics + review queue).

    Production: sink failures would be caught and counted here so monitoring
    can never break resolution.
    """

    def __init__(self, *sinks: MetricsSink) -> None:
        self.sinks = sinks

    def record(self, event: ResolutionEvent) -> None:
        for sink in self.sinks:
            sink.record(event)


class InMemoryMetrics:
    """Reference sink for tests and local runs.

    Production: emit counters/histograms via OpenTelemetry or Prometheus
    (resolver_status_total{status}, resolver_score, resolver_latency_seconds,
    resolver_candidates), ship full events to the log pipeline (e.g. to a
    warehouse table), and alert on shifts in the MATCH/AMBIGUOUS/NOT_FOUND
    mix or p99 latency after a KB or algorithm release.
    """

    def __init__(self) -> None:
        self.status_counts: Counter[str] = Counter()
        self.not_found_inputs: Counter[str] = Counter()
        self.ambiguous_inputs: Counter[str] = Counter()
        self.score_histogram: Counter[float] = Counter()  # bucketed to 0.05
        self.candidate_counts: Counter[int] = Counter()
        self.latencies: list[float] = []

    def record(self, event: ResolutionEvent) -> None:
        self.status_counts[event.status] += 1
        if event.status == Status.NOT_FOUND.value:
            self.not_found_inputs[event.normalized_input] += 1
        elif event.status == Status.AMBIGUOUS.value:
            self.ambiguous_inputs[event.normalized_input] += 1
        if event.score is not None:
            self.score_histogram[round(event.score * 20) / 20] += 1
        self.candidate_counts[len(event.candidates)] += 1
        self.latencies.append(event.latency_s)

    def latency_percentiles(self) -> dict[str, float]:
        if not self.latencies:
            return {}
        ordered = sorted(self.latencies)
        pick = lambda p: ordered[min(len(ordered) - 1, int(p * len(ordered)))]
        return {"p50": pick(0.50), "p95": pick(0.95), "p99": pick(0.99)}


@dataclass(frozen=True)
class ReviewItem:
    normalized_input: str
    status: str
    count: int
    examples: tuple[str, ...]
    candidates: tuple[tuple[str, float], ...]


class ReviewQueue:
    """Collects NOT_FOUND / AMBIGUOUS inputs for human review.

    Workflow (nothing is ever added to the KB automatically):
      1. Aggregate unresolved inputs by normalized form.
      2. Prioritize by frequency (and, in production, by customer impact).
      3. A reviewer decides: new entity, missing alias, or genuinely ambiguous.
      4. The approved change is made to src/techresolve/data/technologies.json in a PR,
         together with new gold rows for the case.
      5. CI runs KB validation, tests and the dev/test eval + regression diff.
    Production: persist items in a DB table with reviewer/decision/PR fields;
    an LLM may pre-fill a *suggested* decision offline, never auto-apply it.
    """

    def __init__(self) -> None:
        self._counts: Counter[tuple[str, str]] = Counter()
        self._examples: dict[tuple[str, str], list[str]] = {}
        self._candidates: dict[tuple[str, str], tuple[tuple[str, float], ...]] = {}

    def record(self, event: ResolutionEvent) -> None:
        if event.status == Status.MATCH.value:
            return
        key = (event.normalized_input, event.status)
        self._counts[key] += 1
        examples = self._examples.setdefault(key, [])
        if event.input not in examples and len(examples) < 5:
            examples.append(event.input)
        self._candidates[key] = event.candidates

    def top(self, n: int = 20) -> list[ReviewItem]:
        ranked = sorted(self._counts.items(), key=lambda item: (-item[1], item[0]))
        return [
            ReviewItem(norm, status, count, tuple(self._examples[(norm, status)]), self._candidates[(norm, status)])
            for (norm, status), count in ranked[:n]
        ]
