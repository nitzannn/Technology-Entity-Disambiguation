import unittest

from helpers import default_resolver
from techresolve import Status


class AliasResolutionTest(unittest.TestCase):
    def assertResolves(self, text, expected_id, match_type=None):
        result = default_resolver().resolve(text)
        self.assertEqual(result.status, Status.MATCH, f"{text!r}: {result.to_dict()}")
        self.assertEqual(result.canonical_id, expected_id, text)
        if match_type:
            self.assertEqual(result.match_type, match_type, text)
        return result

    def test_aws_variants_share_one_canonical(self):
        variants = ["AWS", "Amazon Web Services", "AWS Cloud", "amazon web services", "AMAZON-WEB-SERVICES", "Amazon AWS"]
        results = [self.assertResolves(v, "aws") for v in variants]
        self.assertEqual({r.canonical_name for r in results}, {"AWS"})

    def test_crowdstrike_variants(self):
        for variant in ["CrowdStrike Falcon", "CrowdStrike Falcon®", "crowdstrike falcon", "Falcon Insight", "CrowdStrike EDR"]:
            self.assertResolves(variant, "crowdstrike/falcon")

    def test_renamed_products(self):
        self.assertResolves("Azure AD", "microsoft/entra-id")
        self.assertResolves("Azure Sentinel", "microsoft/sentinel")
        self.assertResolves("Pulse Secure", "ivanti/connect-secure")

    def test_legal_suffix_is_stripped_before_lookup(self):
        self.assertResolves("Okta, Inc.", "okta/workforce-identity", "exact")
        self.assertResolves("Snowflake Inc", "snowflake/snowflake", "exact")

    def test_exact_hit_has_confidence_one(self):
        result = self.assertResolves("Amazon EKS", "aws/eks", "exact")
        self.assertEqual(result.confidence, 1.0)

    def test_realistic_typos_match_fuzzily(self):
        for text, expected in [("Crowdstrik Falcon", "crowdstrike/falcon"),
                               ("CrowdStrike Falcn", "crowdstrike/falcon"),
                               ("Microsft Sentinel", "microsoft/sentinel"),
                               ("Kuberentes", "kubernetes/kubernetes")]:
            result = self.assertResolves(text, expected, "fuzzy")
            self.assertLess(result.confidence, 1.0)


if __name__ == "__main__":
    unittest.main()
