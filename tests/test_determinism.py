import json
import os
import subprocess
import sys
import unittest

from helpers import ROOT, default_resolver
from techresolve import Resolver, Status

SAMPLES = ["Amazon Web Services", "AWS EKS", "Sentinel", "Sentinl", "Crowdstrik Falcon", "Okta, Inc.",
           "Defender", "FooBarDB", "Apache Log4j 2.14.1", "Amazon ECR", ""]


class DeterminismTest(unittest.TestCase):
    def test_repeated_calls_are_identical(self):
        resolver = default_resolver()
        for text in SAMPLES:
            first = resolver.resolve(text).to_dict()
            for _ in range(5):
                self.assertEqual(resolver.resolve(text).to_dict(), first)

    def test_fresh_resolvers_agree(self):
        a, b = Resolver.from_path(), Resolver.from_path()
        for text in SAMPLES:
            self.assertEqual(a.resolve(text).to_dict(), b.resolve(text).to_dict())

    def test_resolving_canonical_name_is_idempotent(self):
        resolver = default_resolver()
        for text in SAMPLES:
            result = resolver.resolve(text)
            if result.status is Status.MATCH:
                again = resolver.resolve(result.canonical_name)
                self.assertEqual((again.status, again.canonical_id), (Status.MATCH, result.canonical_id))

    def test_every_canonical_name_resolves_to_its_entity(self):
        # Covers renamed entities too (e.g. "Azure AKS", "Elasticsearch").
        resolver = default_resolver()
        for entity in resolver.kb.entities.values():
            with self.subTest(id=entity.id):
                result = resolver.resolve(entity.canonical_name)
                self.assertEqual((result.status, result.canonical_id, result.match_type),
                                 (Status.MATCH, entity.id, "exact"))
                self.assertEqual(result.canonical_name, entity.canonical_name)

    def test_output_independent_of_hash_seed(self):
        outputs = set()
        for seed in ("0", "1", "12345", "random"):
            env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(ROOT / "src")}
            proc = subprocess.run([sys.executable, "-m", "techresolve", "--compact", *SAMPLES],
                                  env=env, capture_output=True, text=True, check=True)
            outputs.add(proc.stdout)
        self.assertEqual(len(outputs), 1)
        self.assertEqual(len(next(iter(outputs)).splitlines()), len(SAMPLES))

    def test_versions_are_reported(self):
        payload = default_resolver().resolve("AWS").to_dict()
        for key in ("kb_version", "algorithm_version", "config_hash"):
            self.assertTrue(payload[key], key)
        json.dumps(payload)  # serializable


if __name__ == "__main__":
    unittest.main()
