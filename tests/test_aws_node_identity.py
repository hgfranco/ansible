"""Offline checks for mapping Kubernetes Nodes to EC2 identities."""
import copy
import unittest

from ansible.errors import AnsibleFilterError
from filter_plugins.aws_node_identity import aws_node_provider_ids


class NodeIdentityTests(unittest.TestCase):
    def setUp(self):
        self.nodes = [{
            "metadata": {"name": "kubernetes-worker-01"},
            "spec": {},
            "status": {"addresses": [{"type": "InternalIP", "address": "10.42.1.74"}]},
        }]
        self.instances = [{
            "id": "i-0123456789abcdef0",
            "az": "us-east-1a",
            "private_ip": "10.42.1.74",
            "name": "kubernetes-worker-01",
        }]

    def test_matches_private_identity_and_preserves_matching_provider_id(self):
        expected = "aws:///us-east-1a/i-0123456789abcdef0"
        first = aws_node_provider_ids(self.nodes, self.instances)
        self.assertEqual(first[0]["provider_id"], expected)
        self.nodes[0]["spec"]["providerID"] = expected
        self.assertEqual(aws_node_provider_ids(self.nodes, self.instances), first)

    def test_refuses_conflicting_provider_id(self):
        self.nodes[0]["spec"]["providerID"] = "aws:///us-east-1a/i-11111111111111111"
        with self.assertRaises(AnsibleFilterError):
            aws_node_provider_ids(self.nodes, self.instances)

    def test_refuses_wrong_name_or_address(self):
        for key, value in [("name", "another-cluster"), ("private_ip", "10.42.9.99")]:
            with self.subTest(key=key):
                instances = copy.deepcopy(self.instances)
                instances[0][key] = value
                with self.assertRaises(AnsibleFilterError):
                    aws_node_provider_ids(self.nodes, instances)

    def test_refuses_missing_or_duplicate_instances(self):
        with self.assertRaises(AnsibleFilterError):
            aws_node_provider_ids(self.nodes, [])
        nodes = self.nodes + copy.deepcopy(self.nodes)
        instances = self.instances + copy.deepcopy(self.instances)
        with self.assertRaises(AnsibleFilterError):
            aws_node_provider_ids(nodes, instances)


if __name__ == "__main__":
    unittest.main()
