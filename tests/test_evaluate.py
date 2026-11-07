import unittest

from helpers import GOLD_PATH, entity, small_resolver
from techresolve import Status
from techresolve.evaluation import (GoldRow, Outcome, classify, diff_against_baseline, evaluate, is_correct, is_seen,
                                    load_gold)


def row(status, ids=(), text="x"):
    return GoldRow(text, Status(status), frozenset(ids), "cat", "dev")


MATCH_A = Outcome("MATCH", "a", ("a",))
MATCH_B = Outcome("MATCH", "b", ("b",))
AMB_AB = Outcome("AMBIGUOUS", None, ("a", "b"))
AMB_ABC = Outcome("AMBIGUOUS", None, ("a", "b", "c"))
AMB_A = Outcome("AMBIGUOUS", None, ("a", "c"))
NF = Outcome("NOT_FOUND", None, ("a",))


class ScoringRulesTest(unittest.TestCase):
    def test_match_rules(self):
        expected = row("MATCH", ["a"])
        self.assertTrue(is_correct(expected, MATCH_A))
        self.assertFalse(is_correct(expected, MATCH_B))
        self.assertFalse(is_correct(expected, AMB_AB))
        self.assertFalse(is_correct(expected, NF))

    def test_ambiguous_rules(self):
        expected = row("AMBIGUOUS", ["a", "b"])
        self.assertTrue(is_correct(expected, AMB_AB))
        self.assertTrue(is_correct(expected, AMB_ABC))  # superset is fine
        self.assertFalse(is_correct(expected, AMB_A))   # missing expected candidate
        self.assertFalse(is_correct(expected, MATCH_A))  # MATCH when AMBIGUOUS expected
        self.assertFalse(is_correct(expected, NF))

    def test_not_found_rules(self):
        expected = row("NOT_FOUND")
        self.assertTrue(is_correct(expected, NF))
        self.assertFalse(is_correct(expected, MATCH_A))
        self.assertFalse(is_correct(expected, AMB_AB))

    def test_tp_fp_fn(self):
        self.assertEqual(classify(row("MATCH", ["a"]), MATCH_A), (True, False, False))
        self.assertEqual(classify(row("MATCH", ["a"]), MATCH_B), (False, True, True))  # wrong id: FP and FN
        self.assertEqual(classify(row("MATCH", ["a"]), NF), (False, False, True))
        self.assertEqual(classify(row("NOT_FOUND"), MATCH_A), (False, True, False))
        self.assertEqual(classify(row("AMBIGUOUS", ["a", "b"]), MATCH_A), (False, True, False))
        self.assertEqual(classify(row("AMBIGUOUS", ["a", "b"]), AMB_AB), (False, False, False))


class RegressionDiffTest(unittest.TestCase):
    def test_classification(self):
        rows = [row("MATCH", ["a"], "fixed"), row("AMBIGUOUS", ["a", "b"], "broken"),
                row("MATCH", ["a"], "still_wrong"), row("MATCH", ["a"], "unchanged"), row("NOT_FOUND", (), "new")]
        baseline = {"fixed": NF, "broken": AMB_AB, "still_wrong": NF, "unchanged": MATCH_A}
        current = {"fixed": MATCH_A, "broken": MATCH_A, "still_wrong": MATCH_B, "unchanged": MATCH_A, "new": NF}
        diff = diff_against_baseline(rows, baseline, current)
        self.assertEqual([c["input"] for c in diff["improvement"]], ["fixed"])
        self.assertEqual([c["input"] for c in diff["regression"]], ["broken"])
        self.assertEqual([c["input"] for c in diff["neutral"]], ["still_wrong"])
        self.assertEqual(diff["new_rows"], ["new"])
        # NOT_FOUND -> wrong MATCH is "neutral" by correctness but must still be flagged.
        self.assertEqual(diff["new_fp"], ["broken", "still_wrong"])

    def test_fp_to_different_fp_is_not_new(self):
        rows = [row("NOT_FOUND", (), "s")]
        diff = diff_against_baseline(rows, {"s": MATCH_A}, {"s": MATCH_B})
        self.assertEqual(diff["new_fp"], [])

    def test_wrong_match_to_ambiguous_is_improvement_and_flagged(self):
        rows = [row("AMBIGUOUS", ["a", "b"], "s")]
        diff = diff_against_baseline(rows, {"s": MATCH_A}, {"s": AMB_AB})
        self.assertEqual(len(diff["improvement"]), 1)
        self.assertEqual(diff["new_ambiguous"], ["s"])


class GeneralizationSplitTest(unittest.TestCase):
    def test_seen_vs_novel(self):
        resolver = small_resolver(entity("a", "Acme Widget", aliases=["Widget Pro"]))
        self.assertTrue(is_seen(resolver, "ACME-widget"))      # exact after normalization
        self.assertTrue(is_seen(resolver, "Acme Widget Inc."))  # legal suffix stripped
        self.assertFalse(is_seen(resolver, "Acme Widgte"))      # needs fuzzy
        self.assertFalse(is_seen(resolver, "Inc"))              # normalizes to ""

    def test_report_breakdown(self):
        resolver = small_resolver(entity("a", "Acme Widget"))
        rows = [GoldRow("Acme Widget", Status.MATCH, frozenset({"a"}), "c", "dev"),
                GoldRow("Acme Widgte", Status.MATCH, frozenset({"a"}), "c", "dev"),
                GoldRow("Zzz Unknown", Status.NOT_FOUND, frozenset(), "c", "dev")]
        report = evaluate(resolver, rows)
        self.assertEqual(report["by_surface"]["seen"]["rows"], 1)
        self.assertEqual(report["by_surface"]["novel"]["rows"], 2)


class GoldFileTest(unittest.TestCase):
    def test_gold_loads_and_has_both_splits(self):
        dev, test = load_gold(GOLD_PATH, "dev"), load_gold(GOLD_PATH, "test")
        self.assertGreater(len(test), 0)
        self.assertGreater(len(dev), len(test))
        self.assertEqual({r.category for r in dev}, {r.category for r in test})


if __name__ == "__main__":
    unittest.main()
