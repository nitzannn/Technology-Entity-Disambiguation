import unittest

from helpers import default_resolver, entity, small_resolver
from techresolve import Status


class NearCollisionTest(unittest.TestCase):
    def test_bare_sentinel_is_ambiguous(self):
        result = default_resolver().resolve("Sentinel")
        self.assertEqual(result.status, Status.AMBIGUOUS)
        self.assertIsNone(result.canonical_id)
        self.assertEqual([cid for cid, _ in result.candidates], ["microsoft/sentinel", "sentinelone/singularity"])
        self.assertEqual(result.match_type, "exact")

    def test_qualified_names_are_not_ambiguous(self):
        for text, expected in [("Microsoft Sentinel", "microsoft/sentinel"),
                               ("SentinelOne", "sentinelone/singularity"),
                               ("Sentinel One", "sentinelone/singularity"),
                               ("Sentinel SIEM", "microsoft/sentinel")]:
            result = default_resolver().resolve(text)
            self.assertEqual((result.status, result.canonical_id), (Status.MATCH, expected), text)

    def test_typo_of_shared_alias_stays_ambiguous(self):
        result = default_resolver().resolve("Sentinl")
        self.assertEqual(result.status, Status.AMBIGUOUS)
        self.assertEqual({cid for cid, _ in result.candidates}, {"microsoft/sentinel", "sentinelone/singularity"})

    def test_other_shared_aliases(self):
        for text in ("Defender", "Splunk", "Exchange"):
            self.assertEqual(default_resolver().resolve(text).status, Status.AMBIGUOUS, text)

    def test_exact_collision_stops_before_fuzzy(self):
        resolver = small_resolver(entity("a", "Alpha Widget", aliases=["Widget"]),
                                  entity("b", "Beta Widget", aliases=["Widget"]))
        result = resolver.resolve("widget")
        self.assertEqual((result.status, result.match_type), (Status.AMBIGUOUS, "exact"))

    def test_legal_suffix_collision_is_ambiguous(self):
        resolver = small_resolver(entity("a", "Acme Inc"), entity("b", "Acme Corp"))
        result = resolver.resolve("Acme LLC")
        self.assertEqual((result.status, result.match_type), (Status.AMBIGUOUS, "exact"))
        self.assertEqual([cid for cid, _ in result.candidates], ["a", "b"])

    def test_fuzzy_tie_never_matches_even_with_zero_margin(self):
        resolver = small_resolver(entity("a", "Zeta Gateway"), entity("b", "Zeta Gateway Pro", aliases=["Zeta Gateway"]),
                                  margin=0.0)
        # "Zeta Gateway" collides exactly; a typo of it ties in fuzzy scoring.
        result = resolver.resolve("Zeta Gatway")
        self.assertEqual(result.status, Status.AMBIGUOUS)
        self.assertEqual({cid for cid, _ in result.candidates}, {"a", "b"})


if __name__ == "__main__":
    unittest.main()
