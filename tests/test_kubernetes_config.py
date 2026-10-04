"""Offline checks for network safety, API addressing, and the CNI configuration."""
import importlib.util
import json
from pathlib import Path
import tomllib
import unittest

from jinja2 import Environment, StrictUndefined
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("networks", ROOT / "filter_plugins/kubeadm_networks.py")
NETWORKS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NETWORKS)


class NetworkValidationTests(unittest.TestCase):
    def test_separate_networks(self):
        self.assertTrue(NETWORKS.kubeadm_networks_valid(
            ["10.42.0.0/16", "192.168.0.0/16", "10.96.0.0/12"]
        ))

    def test_overlapping_service_range_is_rejected(self):
        self.assertFalse(NETWORKS.kubeadm_networks_valid(
            ["10.42.0.0/16", "192.168.0.0/16", "10.0.0.0/8"]
        ))

    def test_overlapping_pod_range_is_rejected(self):
        self.assertFalse(NETWORKS.kubeadm_networks_valid(
            ["10.42.0.0/16", "10.42.1.0/24", "10.96.0.0/12"]
        ))

    def test_ipv6_malformed_and_noncanonical_networks_are_rejected(self):
        for network in ["::/64", "invalid", "10.42.0.1/16"]:
            with self.subTest(network=network):
                self.assertFalse(NETWORKS.kubeadm_networks_valid(
                    [network, "192.168.0.0/16", "10.96.0.0/12"]
                ))

    def test_private_address_must_belong_to_vpc(self):
        self.assertTrue(NETWORKS.kubeadm_address_in_network("10.42.1.10", "10.42.0.0/16"))
        for address in ["192.0.2.10", "::1", "invalid"]:
            with self.subTest(address=address):
                self.assertFalse(NETWORKS.kubeadm_address_in_network(address, "10.42.0.0/16"))


class ConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.variables = yaml.safe_load((ROOT / "inventory/group_vars/kubernetes.yml").read_text())
        cls.variables.update(
            private_ip_address="10.42.1.10", inventory_hostname="kubernetes-control"
        )
        cls.environment = Environment(undefined=StrictUndefined)
        cls.environment.filters["to_json"] = json.dumps

    def render(self, path):
        return self.environment.from_string((ROOT / path).read_text()).render(self.variables)

    def test_cluster_uses_private_endpoint_and_loopback_certificate_san(self):
        configs = list(yaml.safe_load_all(self.render("roles/kubeadm_control_plane/templates/init.yml.j2")))
        init, cluster, kubelet = configs
        self.assertEqual(init["apiVersion"], "kubeadm.k8s.io/v1beta4")
        self.assertEqual(init["localAPIEndpoint"]["advertiseAddress"], "10.42.1.10")
        self.assertEqual(cluster["controlPlaneEndpoint"], "10.42.1.10:6443")
        self.assertIn("127.0.0.1", cluster["apiServer"]["certSANs"])
        self.assertEqual(kubelet["cgroupDriver"], "systemd")
        self.assertTrue(kubelet["failSwapOn"])

    def test_custom_pod_network_is_used_by_both_kubeadm_and_calico(self):
        original = self.variables["kubernetes_pod_cidr"]
        self.variables["kubernetes_pod_cidr"] = "172.20.0.0/16"
        try:
            cluster = list(yaml.safe_load_all(
                self.render("roles/kubeadm_control_plane/templates/init.yml.j2")
            ))[1]
            calico = yaml.safe_load(self.render("roles/calico/templates/installation.yml.j2"))
            network = calico["spec"]["calicoNetwork"]
            self.assertEqual(cluster["networking"]["podSubnet"], "172.20.0.0/16")
            self.assertEqual(network["ipPools"][0]["cidr"], "172.20.0.0/16")
            self.assertEqual(network["ipPools"][0]["encapsulation"], "VXLAN")
            self.assertEqual(network["nodeAddressAutodetectionV4"]["kubernetes"], "NodeInternalIP")
        finally:
            self.variables["kubernetes_pod_cidr"] = original

    def test_containerd_enables_cri_systemd_cgroups_and_v2_runc(self):
        runtime = tomllib.loads(self.render("roles/kubernetes_node/templates/containerd.toml.j2"))
        self.assertNotIn("cri", runtime.get("disabled_plugins", []))
        runc = runtime["plugins"]["io.containerd.grpc.v1.cri"]["containerd"]["runtimes"]["runc"]
        self.assertEqual(runc["runtime_type"], "io.containerd.runc.v2")
        self.assertTrue(runc["options"]["SystemdCgroup"])


if __name__ == "__main__":
    unittest.main()
