"""Validate the pinned Metrics Server chart and its TLS configuration."""
import sys

import yaml

with open(sys.argv[1], encoding="utf-8") as manifest:
    docs = [doc for doc in yaml.safe_load_all(manifest) if doc]
resources = {(doc["kind"], doc["metadata"]["name"]): doc for doc in docs}
deployment = resources[("Deployment", "metrics-server")]
pod = deployment["spec"]["template"]["spec"]
assert deployment["spec"]["replicas"] == 1
assert not pod.get("hostNetwork", False)
container = next(c for c in pod["containers"] if c["name"] == "metrics-server")
assert container["image"] == "registry.k8s.io/metrics-server/metrics-server:v0.9.0"
assert "--kubelet-preferred-address-types=InternalIP" in container["args"]
assert ("--kubelet-insecure-tls" in container["args"]) == ("--kubeadm" in sys.argv)
assert container["resources"]["requests"] == {"cpu": "100m", "memory": "200Mi"}
assert container["readinessProbe"]["httpGet"]["path"] == "/readyz"
assert container["securityContext"]["runAsNonRoot"] is True
api = resources[("APIService", "v1beta1.metrics.k8s.io")]["spec"]
assert api["service"]["namespace"] == "kube-system"
assert api["service"]["name"] == "metrics-server"
assert not api.get("insecureSkipTLSVerify", False)
assert api["caBundle"] == resources[("Secret", "metrics-server")]["data"]["tls.crt"]
assert any(doc["kind"] == "ClusterRoleBinding" for doc in docs)
print("Pinned Metrics Server rendering validated.")
