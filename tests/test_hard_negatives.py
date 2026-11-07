import unittest

from helpers import default_resolver
from techresolve import Status


class HardNegativeTest(unittest.TestCase):
    def resolve_id(self, text):
        result = default_resolver().resolve(text)
        return result.canonical_id if result.status is Status.MATCH else result.status

    def test_aws_is_not_aws_eks(self):
        self.assertEqual(self.resolve_id("Amazon Web Services"), "aws")
        self.assertEqual(self.resolve_id("AWS EKS"), "aws/eks")
        self.assertNotEqual(self.resolve_id("Amazon Web Services"), self.resolve_id("AWS EKS"))

    def test_sibling_services_do_not_collapse(self):
        ids = {self.resolve_id(t) for t in ("AWS EKS", "AWS ECS", "AWS EC2", "AWS S3")}
        self.assertEqual(ids, {"aws/eks", "aws/ecs", "aws/ec2", "aws/s3"})

    def test_unknown_sibling_is_not_forced_onto_known_one(self):
        self.assertEqual(self.resolve_id("Amazon ECR"), Status.NOT_FOUND)
        self.assertEqual(self.resolve_id("Fortinet FortiWeb"), Status.NOT_FOUND)
        self.assertEqual(self.resolve_id("Spring Cloud"), Status.NOT_FOUND)

    def test_languages_are_out_of_scope(self):
        # Languages are not products (docs/DESIGN.md, Scope); jQuery and Node.js stay.
        for text in ("Java", "JavaScript", "Python", "C++", "C#", "C"):
            self.assertEqual(self.resolve_id(text), Status.NOT_FOUND, text)

    def test_parent_is_not_child(self):
        self.assertEqual(self.resolve_id("Azure"), "microsoft/azure")
        self.assertEqual(self.resolve_id("Azure Kubernetes Service"), "microsoft/aks")
        self.assertEqual(self.resolve_id("Google Cloud"), "google/cloud")
        self.assertEqual(self.resolve_id("Google Kubernetes Engine"), "google/gke")

    def test_vendor_only_names_are_not_found(self):
        for vendor in ("CrowdStrike", "Microsoft", "Amazon"):
            self.assertEqual(self.resolve_id(vendor), Status.NOT_FOUND, vendor)

    def test_unknown_and_empty_inputs(self):
        for text in ("FooBarDB", "Wireshark", "", "   ", "™®"):
            self.assertEqual(self.resolve_id(text), Status.NOT_FOUND, repr(text))


if __name__ == "__main__":
    unittest.main()
