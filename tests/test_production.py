import unittest

from helpers import entity, small_resolver
from techresolve import Resolver
from techresolve.production import FanOutSink, InMemoryMetrics, ResolutionEvent, ReviewQueue


def resolver_with(sink):
    r = small_resolver(entity("a", "Alpha Widget", aliases=["Widget"]), entity("b", "Beta Widget", aliases=["Widget"]))
    r.sink = sink
    return r


class ResolutionEventTest(unittest.TestCase):
    def test_event_carries_result_and_versions(self):
        captured = []
        r = resolver_with(type("Capture", (), {"record": lambda self, e: captured.append(e)})())
        result = r.resolve("Alpha Widget")
        (event,) = captured
        self.assertIsInstance(event, ResolutionEvent)
        self.assertEqual((event.input, event.normalized_input, event.status, event.canonical_id),
                         ("Alpha Widget", "alpha widget", "MATCH", "a"))
        self.assertEqual((event.kb_version, event.config_hash), (result.kb_version, result.config_hash))
        self.assertGreaterEqual(event.latency_s, 0.0)

    def test_no_sink_is_fine(self):
        self.assertIsNone(Resolver.from_path().sink)


class InMemoryMetricsTest(unittest.TestCase):
    def test_aggregates(self):
        metrics = InMemoryMetrics()
        r = resolver_with(metrics)
        for text in ("Alpha Widget", "widget", "Widget", "nothing here", "Nothing Here"):
            r.resolve(text)
        self.assertEqual(dict(metrics.status_counts), {"MATCH": 1, "AMBIGUOUS": 2, "NOT_FOUND": 2})
        self.assertEqual(metrics.ambiguous_inputs["widget"], 2)
        self.assertEqual(metrics.not_found_inputs["nothing here"], 2)
        self.assertEqual(metrics.score_histogram[1.0], 1)
        self.assertEqual(sum(metrics.candidate_counts.values()), 5)
        self.assertEqual(set(metrics.latency_percentiles()), {"p50", "p95", "p99"})

    def test_empty_latency(self):
        self.assertEqual(InMemoryMetrics().latency_percentiles(), {})


class ReviewQueueTest(unittest.TestCase):
    def test_prioritizes_by_frequency_and_ignores_matches(self):
        queue = ReviewQueue()
        r = resolver_with(queue)
        for text in ("Alpha Widget", "widget", "Widget", "WIDGET", "nothing here"):
            r.resolve(text)
        items = queue.top()
        self.assertEqual([(i.normalized_input, i.status, i.count) for i in items],
                         [("widget", "AMBIGUOUS", 3), ("nothing here", "NOT_FOUND", 1)])
        self.assertEqual(items[0].examples, ("widget", "Widget", "WIDGET"))
        self.assertEqual([cid for cid, _ in items[0].candidates], ["a", "b"])

    def test_examples_capped(self):
        queue = ReviewQueue()
        r = resolver_with(queue)
        for i in range(8):
            r.resolve("nothing" + " " * i + " here")  # same normalized form, distinct raw inputs
        self.assertEqual(len(queue.top()[0].examples), 5)


class FanOutSinkTest(unittest.TestCase):
    def test_forwards_to_all_sinks(self):
        metrics, queue = InMemoryMetrics(), ReviewQueue()
        r = resolver_with(FanOutSink(metrics, queue))
        r.resolve("widget")
        self.assertEqual(metrics.status_counts["AMBIGUOUS"], 1)
        self.assertEqual(queue.top()[0].normalized_input, "widget")


if __name__ == "__main__":
    unittest.main()
