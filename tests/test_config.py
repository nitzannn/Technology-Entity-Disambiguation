import unittest
from dataclasses import replace

import helpers  # noqa: F401
from techresolve import ResolverConfig


class ConfigValidationTest(unittest.TestCase):
    def test_defaults_are_valid(self):
        ResolverConfig()

    def test_boundary_values_accepted(self):
        ResolverConfig(threshold=0.0, margin=0.0, w_jaccard=1.0, w_sequence=0.0, top_k=1,
                       short_token_len=0, min_fuzzy_len=0, not_found_candidates=0)
        ResolverConfig(threshold=1.0, margin=1.0, token_sim_threshold=1.0)

    def test_invalid_values_rejected(self):
        bad = [
            {"threshold": 1.2}, {"threshold": -0.1}, {"margin": -0.01}, {"margin": 1.5},
            {"token_sim_threshold": 2}, {"w_jaccard": 1.0, "w_sequence": 1.0},  # sum 2 -> scores > 1
            {"w_jaccard": -0.5, "w_sequence": 1.5}, {"top_k": 0}, {"top_k": 2.5},
            {"short_token_len": -1}, {"min_fuzzy_len": -1}, {"not_found_candidates": -1},
            {"threshold": "0.8"}, {"top_k": True},
        ]
        for kwargs in bad:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                ResolverConfig(**kwargs)

    def test_replace_is_validated(self):
        with self.assertRaises(ValueError):
            replace(ResolverConfig(), top_k=0)

    def test_hash_changes_with_values(self):
        self.assertNotEqual(ResolverConfig().config_hash(), ResolverConfig(threshold=0.81).config_hash())
        self.assertEqual(ResolverConfig().config_hash(), ResolverConfig().config_hash())


if __name__ == "__main__":
    unittest.main()
