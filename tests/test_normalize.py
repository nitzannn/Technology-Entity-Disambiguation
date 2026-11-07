import unittest

import helpers  # noqa: F401
from techresolve.normalize import normalize


class NormalizeTest(unittest.TestCase):
    def test_case_and_whitespace(self):
        self.assertEqual(normalize("  Amazon   Web\tServices "), "amazon web services")

    def test_nfkc_and_fullwidth(self):
        self.assertEqual(normalize("ＡＷＳ"), "aws")

    def test_trademark_symbols_removed(self):
        self.assertEqual(normalize("CrowdStrike Falcon®"), "crowdstrike falcon")
        self.assertEqual(normalize("Splunk™ Enterprise"), "splunk enterprise")

    def test_ampersand(self):
        self.assertEqual(normalize("AT&T"), "at and t")

    def test_punctuation_to_space(self):
        self.assertEqual(normalize("log4j-core"), "log4j core")
        self.assertEqual(normalize("Node.js"), "node js")
        self.assertEqual(normalize("snake_case/path"), "snake case path")

    def test_plus_and_hash_kept(self):
        self.assertEqual(normalize("C++"), "c++")
        self.assertEqual(normalize("C#"), "c#")
        self.assertNotEqual(normalize("C++"), normalize("C#"))

    def test_versions_preserved(self):
        self.assertEqual(normalize("Apache Log4j 2.14.1"), "apache log4j 2 14 1")

    def test_meaningful_words_preserved(self):
        for word in ("cloud", "platform", "service", "software", "suite"):
            self.assertIn(word, normalize(f"Acme {word.title()}"))

    def test_idempotent(self):
        for text in ("AWS Cloud", "CrowdStrike Falcon®", "C++", "log4j-core", "Okta, Inc."):
            self.assertEqual(normalize(normalize(text)), normalize(text))


class LegalSuffixTest(unittest.TestCase):
    def test_strips_trailing_legal_suffixes(self):
        self.assertEqual(normalize("Okta, Inc."), "okta")
        self.assertEqual(normalize("Acme Holdings Ltd"), "acme holdings")
        self.assertEqual(normalize("Foo Corp LLC"), "foo")

    def test_keeps_non_trailing_suffix_tokens(self):
        self.assertEqual(normalize("Corp Connect Suite"), "corp connect suite")

    def test_keeps_limited(self):
        self.assertEqual(normalize("Acme Limited"), "acme limited")

    def test_keeps_meaningful_words(self):
        self.assertEqual(normalize("Splunk Cloud"), "splunk cloud")

    def test_empty_result(self):
        self.assertEqual(normalize("Inc."), "")
        self.assertEqual(normalize(""), "")


if __name__ == "__main__":
    unittest.main()
