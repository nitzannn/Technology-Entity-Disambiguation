import re
import unittest

from helpers import KB_PATH, entity, small_resolver
from techresolve import KBValidationError, Status, build_kb, load_kb


def kb(*entities):
    return build_kb({"schema_version": 1, "entities": list(entities)})


class ValidationTest(unittest.TestCase):
    def test_bundled_kb_is_valid(self):
        loaded = load_kb(KB_PATH)
        self.assertGreater(len(loaded.entities), 50)
        self.assertEqual(len(loaded.version), 64)

    def test_duplicate_id(self):
        with self.assertRaisesRegex(KBValidationError, "duplicate id"):
            kb(entity("a", "A"), entity("a", "A2"))

    def test_dangling_parent(self):
        with self.assertRaisesRegex(KBValidationError, "parent_id"):
            kb(entity("a", "A", parent="missing"))

    def test_parent_cycle(self):
        with self.assertRaisesRegex(KBValidationError, "parent cycle"):
            kb(entity("a", "A", parent="b"), entity("b", "B", parent="a"))

    def test_dangling_redirect(self):
        with self.assertRaisesRegex(KBValidationError, "unknown id"):
            kb(entity("a", "A"), {"id": "old", "redirect_to": "missing"})

    def test_redirect_cycle(self):
        with self.assertRaisesRegex(KBValidationError, "redirect cycle"):
            kb(entity("a", "A"), {"id": "x", "redirect_to": "y"}, {"id": "y", "redirect_to": "x"})

    def test_redirect_stub_with_entity_fields_rejected(self):
        with self.assertRaisesRegex(KBValidationError, "must not have fields"):
            kb(entity("a", "A"), {"id": "old", "redirect_to": "a", "canonical_name": "Old"})

    def test_duplicate_id_between_stub_and_entity(self):
        with self.assertRaisesRegex(KBValidationError, "duplicate id"):
            kb(entity("a", "A"), {"id": "a", "redirect_to": "a"})

    def test_parent_redirecting_to_self_is_a_cycle(self):
        with self.assertRaisesRegex(KBValidationError, "own parent"):
            kb(entity("a", "A", parent="old"), {"id": "old", "redirect_to": "a"})

    def test_parent_cycle_through_redirect(self):
        with self.assertRaisesRegex(KBValidationError, "parent cycle"):
            kb(entity("a", "A", parent="old_b"), entity("b", "B", parent="a"), {"id": "old_b", "redirect_to": "b"})

    def test_empty_alias_rejected(self):
        with self.assertRaisesRegex(KBValidationError, "empty string"):
            kb(entity("a", "A", aliases=["™"]))

    def test_unsupported_schema(self):
        with self.assertRaises(KBValidationError):
            build_kb({"schema_version": 99, "entities": []})


class CanonicalNameLintTest(unittest.TestCase):
    """Canonical-name format rules (docs/DESIGN.md) checked on every real entity."""

    TRAILING_VERSION = re.compile(r"\s\d+(\.\d+)*$")
    # Brand names whose trailing number is part of the product name, not a version.
    NUMERIC_BRAND_NAMES = {"Microsoft 365"}

    def entities(self):
        return sorted(load_kb(KB_PATH).entities.values(), key=lambda e: e.id)  # redirect stubs excluded

    def test_no_stray_whitespace(self):
        for e in self.entities():
            with self.subTest(id=e.id):
                self.assertEqual(e.canonical_name, e.canonical_name.strip())
                self.assertNotIn("  ", e.canonical_name)

    def test_no_trailing_version_number(self):
        for e in self.entities():
            if e.canonical_name in self.NUMERIC_BRAND_NAMES:
                continue
            with self.subTest(id=e.id):
                self.assertIsNone(self.TRAILING_VERSION.search(e.canonical_name), e.canonical_name)

    def test_vendor_not_repeated(self):
        # "Elastic Elasticsearch" fails: the vendor stands alone and recurs inside
        # another word. "Elasticsearch" (prefix only) and "Elastic Security" pass.
        for e in self.entities():
            name, vendor = e.canonical_name.casefold(), e.vendor.casefold()
            standalone = re.search(rf"\b{re.escape(vendor)}\b", name)
            with self.subTest(id=e.id):
                self.assertFalse(standalone and name.count(vendor) >= 2, e.canonical_name)

    def test_lint_rules_catch_known_bad_names(self):
        self.assertIsNotNone(self.TRAILING_VERSION.search("Microsoft Exchange Server 2019"))
        self.assertIsNotNone(self.TRAILING_VERSION.search("Apache Log4j 2.14.1"))
        self.assertIsNone(self.TRAILING_VERSION.search("Microsoft Exchange Server"))
        name, vendor = "elastic elasticsearch", "elastic"
        self.assertTrue(re.search(rf"\b{vendor}\b", name) and name.count(vendor) >= 2)


class RedirectAndIdempotencyTest(unittest.TestCase):
    def test_redirect_chain_resolves_to_final_target(self):
        loaded = kb(entity("new", "New"), {"id": "mid", "redirect_to": "new"}, {"id": "old", "redirect_to": "mid"})
        self.assertEqual(loaded.final_id("old"), "new")
        self.assertEqual(loaded.final_id("mid"), "new")
        self.assertEqual(loaded.final_id("new"), "new")

    def test_redirect_stubs_never_appear_in_index(self):
        resolver = small_resolver(entity("new", "New Product", aliases=["Old Product"]),
                                  {"id": "old", "redirect_to": "new"})
        ids = set().union(*resolver.indexes.exact_alias_index.values())
        self.assertEqual(ids, {"new"})
        result = resolver.resolve("Old Product")
        self.assertEqual((result.status, result.canonical_id), (Status.MATCH, "new"))

    def test_bundled_redirect(self):
        loaded = load_kb(KB_PATH)
        self.assertEqual(loaded.final_id("microsoft/azure-sentinel"), "microsoft/sentinel")


class RedirectMergeTest(unittest.TestCase):
    """Regression tests for merges: aliases, parents, and old-id lookup."""

    def merged(self):
        return small_resolver(
            entity("acme/suite", "Acme Suite", aliases=["Acme One"]),
            entity("acme/addon", "Acme Addon", parent="acme/legacy"),
            entity("other/one", "Other One", aliases=["Shared Former Name"]),
            {"id": "acme/legacy", "redirect_to": "acme/suite",
             "aliases": ["Acme Legacy", "Acme One", "Shared Former Name"]},
            {"id": "acme/older", "redirect_to": "acme/legacy", "aliases": ["Acme Classic"]},
        )

    def test_stub_aliases_merge_into_final_target(self):
        resolver = self.merged()
        self.assertEqual(resolver.kb.entities["acme/suite"].aliases,
                         ("Acme Suite", "Acme One", "Acme Legacy", "Shared Former Name", "Acme Classic"))
        for name in ("Acme Legacy", "Acme Classic"):  # incl. alias from a two-hop chain
            result = resolver.resolve(name)
            self.assertEqual((result.status, result.canonical_id), (Status.MATCH, "acme/suite"), name)

    def test_alias_on_both_stub_and_target_is_not_ambiguous(self):
        result = self.merged().resolve("Acme One")
        self.assertEqual((result.status, result.canonical_id), (Status.MATCH, "acme/suite"))

    def test_merged_alias_shared_with_another_entity_is_ambiguous(self):
        result = self.merged().resolve("Shared Former Name")
        self.assertEqual(result.status, Status.AMBIGUOUS)
        self.assertEqual([cid for cid, _ in result.candidates], ["acme/suite", "other/one"])

    def test_parent_pointing_to_stub_is_rewritten(self):
        self.assertEqual(self.merged().kb.entities["acme/addon"].parent_id, "acme/suite")

    def test_lookup_id_follows_redirects(self):
        resolver = self.merged()
        self.assertEqual(resolver.lookup_id("acme/older").id, "acme/suite")
        self.assertEqual(resolver.lookup_id("acme/legacy").canonical_name, "Acme Suite")
        self.assertEqual(resolver.lookup_id("acme/suite").id, "acme/suite")
        self.assertIsNone(resolver.lookup_id("never/existed"))

    def test_stubs_never_returned_as_canonical_ids(self):
        resolver = self.merged()
        ids = set().union(*resolver.indexes.exact_alias_index.values())
        self.assertTrue(ids.isdisjoint(resolver.kb.redirects))

    def test_bundled_old_id_lookup(self):
        from techresolve import lookup_id
        self.assertEqual(lookup_id("microsoft/azure-sentinel").id, "microsoft/sentinel")

    def test_bundled_appliance_merged_into_its_os(self):
        from techresolve import lookup_id, resolve
        self.assertEqual(lookup_id("fortinet/fortigate").id, "fortinet/fortios")
        result = resolve("FortiGate")
        self.assertEqual((result.status, result.canonical_id), (Status.MATCH, "fortinet/fortios"))

    def test_duplicate_alias_within_entity_is_deduplicated(self):
        with self.assertLogs("techresolve.kb", level="WARNING"):
            loaded = kb(entity("a", "Alpha", aliases=["Alpha One", "alpha-one", "ALPHA ONE"]))
        self.assertEqual(loaded.entities["a"].aliases, ("Alpha", "Alpha One"))

    def test_duplicate_alias_does_not_change_resolution(self):
        once = small_resolver(entity("a", "Alpha", aliases=["Alpha One"]))
        with self.assertLogs("techresolve.kb", level="WARNING"):
            twice = small_resolver(entity("a", "Alpha", aliases=["Alpha One", "Alpha One"]))
        self.assertEqual(once.indexes.exact_alias_index, twice.indexes.exact_alias_index)
        self.assertEqual(once.indexes.trigram_index, twice.indexes.trigram_index)


if __name__ == "__main__":
    unittest.main()
