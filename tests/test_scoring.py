import unittest

from helpers import entity, small_resolver
from techresolve import ResolverConfig, Status
from techresolve.retrieval import retrieve
from techresolve.scoring import alias_score, soft_token_jaccard

CFG = ResolverConfig()


class SoftJaccardTest(unittest.TestCase):
    def test_typo_tokens_pair(self):
        self.assertEqual(soft_token_jaccard("crowdstrik falcon", "crowdstrike falcon", CFG), 1.0)

    def test_short_tokens_require_exact_match(self):
        # "eks" vs "ecs" -> no pair; only "aws" matches: 1 / (2 + 2 - 1)
        self.assertAlmostEqual(soft_token_jaccard("aws eks", "aws ecs", CFG), 1 / 3)
        self.assertEqual(soft_token_jaccard("eks", "eks", CFG), 1.0)

    def test_short_token_policy_is_configurable(self):
        lenient = ResolverConfig(short_token_len=0, token_sim_threshold=0.6)
        self.assertEqual(soft_token_jaccard("eks", "ecs", lenient), 1.0)

    def test_pairing_is_one_to_one(self):
        # Both "falcon" tokens on the left are similar to the single right token;
        # only one may pair: 1 / (2 + 1 - 1) = 0.5
        self.assertEqual(soft_token_jaccard("falcon falcons", "falcon", CFG), 0.5)
        self.assertEqual(soft_token_jaccard("falcon", "falcon falcon", CFG), 0.5)

    def test_greedy_prefers_best_pair(self):
        # "sentinal" pairs with "sentinel" (closest), leaving "sentinels" for nothing.
        self.assertAlmostEqual(soft_token_jaccard("sentinal", "sentinels sentinel", CFG), 0.5)

    def test_empty(self):
        self.assertEqual(soft_token_jaccard("", "aws", CFG), 0.0)

    def test_scores_in_unit_interval(self):
        for a, b in [("aws", "aws"), ("foo", "bar baz"), ("crowdstrik", "crowdstrike falcon")]:
            self.assertTrue(0.0 <= alias_score(a, b, CFG) <= 1.0)
        self.assertEqual(alias_score("aws eks", "aws eks", CFG), 1.0)


class DecisionTest(unittest.TestCase):
    def test_contender_below_threshold_but_within_margin_is_included(self):
        resolver = small_resolver(entity("a", "Orion Monitor"), entity("b", "Orion Monitors Pro"),
                                  threshold=0.80, margin=0.5)
        result = resolver.resolve("Orion Monitr")
        scores = dict(result.candidates)
        self.assertEqual(result.status, Status.AMBIGUOUS)
        self.assertGreaterEqual(scores["a"], 0.80)
        self.assertLess(scores["b"], 0.80)  # below threshold, still a contender

    def test_clear_winner_matches(self):
        resolver = small_resolver(entity("a", "Orion Monitor"), entity("b", "Vega Scanner"))
        result = resolver.resolve("Orion Monitr")
        self.assertEqual((result.status, result.canonical_id, result.match_type), (Status.MATCH, "a", "fuzzy"))

    def test_below_threshold_is_not_found_with_review_candidates(self):
        resolver = small_resolver(entity("a", "Orion Monitor"))
        result = resolver.resolve("Orbital Scanner")
        self.assertEqual(result.status, Status.NOT_FOUND)
        self.assertIsNone(result.canonical_id)

    def test_short_inputs_skip_fuzzy(self):
        resolver = small_resolver(entity("a", "Okta"))
        self.assertEqual(resolver.resolve("okt").status, Status.NOT_FOUND)

    def test_max_aggregation_not_average(self):
        # Many dissimilar aliases must not dilute the one close alias.
        many = small_resolver(entity("a", "Orion Monitor", aliases=[f"Unrelated Name {i}" for i in range(10)]))
        few = small_resolver(entity("a", "Orion Monitor"))
        self.assertEqual(many.resolve("Orion Monitr").confidence, few.resolve("Orion Monitr").confidence)


class RetrievalTest(unittest.TestCase):
    def test_shared_alias_expands_to_all_entities(self):
        resolver = small_resolver(entity("a", "Alpha", aliases=["Shared Name"]),
                                  entity("b", "Beta", aliases=["Shared Name"]), top_k=1)
        self.assertEqual(resolver.retrieved_entity_ids("Shared Nme"), frozenset({"a", "b"}))

    def test_topk_is_a_hard_bound(self):
        resolver = small_resolver(*(entity(f"e{i}", f"abc{chr(97 + i)}") for i in range(10)))
        for k in (1, 3, 5):
            self.assertEqual(len(retrieve("abc", resolver.indexes, top_k=k)), k)

    def test_ties_broken_by_length_similarity_then_alias(self):
        # Same shared-trigram count; the alias closer in length ranks first,
        # then exact ties fall back to alphabetical order.
        resolver = small_resolver(entity("a", "abcd extra long"), entity("b", "abcz"), entity("c", "abcy"))
        self.assertEqual(retrieve("abcd", resolver.indexes, top_k=3)[0], "abcd extra long")  # more shared trigrams
        self.assertEqual(retrieve("abc", resolver.indexes, top_k=3), ["abcy", "abcz", "abcd extra long"])

    def test_too_small_k_can_hide_an_ambiguous_competitor(self):
        # Documents the K trade-off: the competitor's alias is cut at K=1, so
        # a genuinely ambiguous typo becomes a MATCH. Larger K restores it.
        ents = (entity("a", "Orion Monitor"), entity("b", "Orion Monitors"))
        self.assertEqual(small_resolver(*ents, top_k=1).resolve("Orion Monitr").status, Status.MATCH)
        self.assertEqual(small_resolver(*ents, top_k=2).resolve("Orion Monitr").status, Status.AMBIGUOUS)

    def test_retrieval_is_deterministic_under_reordered_kb(self):
        ents = [entity(f"e{i}", f"widget {chr(97 + i)}") for i in range(8)]
        forward = small_resolver(*ents, top_k=3)
        backward = small_resolver(*reversed(ents), top_k=3)
        self.assertEqual(retrieve("widget", forward.indexes, 3), retrieve("widget", backward.indexes, 3))


if __name__ == "__main__":
    unittest.main()
