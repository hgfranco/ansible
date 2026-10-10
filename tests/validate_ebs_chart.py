"""Validate the actual Helm rendering without connecting to AWS or Kubernetes."""
import sys

import yaml

with open(sys.argv[1], encoding="utf-8") as manifest:
    docs = [doc for doc in yaml.safe_load_all(manifest) if doc]
resources = {(doc["kind"], doc["metadata"]["name"]): doc for doc in docs}
controller = resources[("Deployment", "ebs-csi-controller")]["spec"]
pod = controller["template"]["spec"]
assert controller["replicas"] == 1
assert pod["hostNetwork"] is True
assert pod["dnsPolicy"] == "ClusterFirstWithHostNet"
plugin = next(c for c in pod["containers"] if c["name"] == "ebs-plugin")
assert plugin["image"].endswith(":v1.66.1")
assert {"name": "AWS_REGION", "value": "us-east-1"} in plugin["env"]
assert not any(e["name"] in {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"}
               and not e.get("valueFrom", {}).get("secretKeyRef", {}).get("optional")
               for e in plugin["env"])
node_pod = resources[("DaemonSet", "ebs-csi-node")]["spec"]["template"]["spec"]
assert node_pod["hostNetwork"] is True
controller_ports = {
    (p.get("protocol", "TCP"), p.get("hostPort", p["containerPort"]))
    for c in pod["containers"] for p in c.get("ports", [])
}
node_ports = {
    (p.get("protocol", "TCP"), p.get("hostPort", p["containerPort"]))
    for c in node_pod["containers"] for p in c.get("ports", [])
}
assert controller_ports.isdisjoint(node_ports), "Controller/node host ports conflict"
healthz = next(p for p in plugin["ports"] if p["name"] == "healthz")
assert healthz["containerPort"] == 9810
for probe_name in ("livenessProbe", "readinessProbe"):
    assert plugin[probe_name]["httpGet"]["port"] == "healthz"
probe = next(c for c in pod["containers"] if c["name"] == "liveness-probe")
assert "--http-endpoint=:9810" in probe["args"]
assert not any(arg.startswith("--health-port=") for arg in probe["args"])
assert ("CSIDriver", "ebs.csi.aws.com") in resources
assert not any(doc["kind"] in {"StorageClass", "PersistentVolumeClaim"} for doc in docs)
print("Pinned EBS chart rendering validated.")
