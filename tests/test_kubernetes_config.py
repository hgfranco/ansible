"""Offline checks for network safety, API addressing, and the CNI configuration."""
import importlib.util
import json
import os
import re
import subprocess
import tempfile
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
        self.assertEqual(runtime["version"], 3)
        self.assertNotIn("io.containerd.grpc.v1.cri", runtime["plugins"])
        images = runtime["plugins"]["io.containerd.cri.v1.images"]
        self.assertEqual(images["pinned_images"]["sandbox"], "registry.k8s.io/pause:3.10.1")
        runc = runtime["plugins"]["io.containerd.cri.v1.runtime"]["containerd"]["runtimes"]["runc"]
        self.assertEqual(runc["runtime_type"], "io.containerd.runc.v2")
        self.assertTrue(runc["options"]["SystemdCgroup"])

    def test_version_guard_accepts_observed_output_and_rejects_other_schemas(self):
        tasks = yaml.safe_load((ROOT / "roles/kubernetes_node/tasks/main.yml").read_text())
        guard = next(task for task in tasks if task["name"] == "Confirm the containerd configuration schema is supported")
        expression = guard["ansible.builtin.assert"]["that"][0]
        pattern = expression.split("search('", 1)[1].rsplit("')", 1)[0]
        self.assertIsNotNone(re.search(pattern, "containerd github.com/containerd/containerd/v2 2.2.1"))
        for version in ["1.7.28", "2.1.0", "3.0.0", "2.20.1"]:
            self.assertIsNone(re.search(pattern, "containerd github.com/containerd/containerd/v2 " + version))

    @unittest.skipUnless(os.environ.get("CONTAINERD_TEST_BINARY"), "Native binary is supplied by CI")
    def test_native_containerd_loads_expected_cri_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.toml"
            config.write_text(self.render("roles/kubernetes_node/templates/containerd.toml.j2"))
            result = subprocess.run(
                [os.environ["CONTAINERD_TEST_BINARY"], "--config", str(config), "config", "dump"],
                check=True, capture_output=True, text=True,
            )
        loaded = tomllib.loads(result.stdout)
        self.assertEqual(loaded["version"], 3)
        self.assertNotIn("cri", loaded.get("disabled_plugins", []))
        runtime = loaded["plugins"]["io.containerd.cri.v1.runtime"]["containerd"]
        self.assertEqual(runtime["default_runtime_name"], "runc")
        self.assertEqual(runtime["runtimes"]["runc"]["runtime_type"], "io.containerd.runc.v2")
        self.assertTrue(runtime["runtimes"]["runc"]["options"]["SystemdCgroup"])
        images = loaded["plugins"]["io.containerd.cri.v1.images"]
        self.assertEqual(images["snapshotter"], "overlayfs")
        self.assertEqual(images["pinned_images"]["sandbox"], "registry.k8s.io/pause:3.10.1")


if __name__ == "__main__":
    unittest.main()
