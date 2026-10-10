"""Enable controller IMDS access without increasing EC2's metadata hop limit."""
import sys

import yaml

documents = list(yaml.safe_load_all(sys.stdin))
controllers = [
    doc for doc in documents
    if doc and doc.get("kind") == "Deployment"
    and doc.get("metadata", {}).get("name") == "ebs-csi-controller"
]
if len(controllers) != 1:
    raise SystemExit("Expected exactly one ebs-csi-controller Deployment")
pod_spec = controllers[0]["spec"]["template"]["spec"]
pod_spec["hostNetwork"] = True
pod_spec["dnsPolicy"] = "ClusterFirstWithHostNet"
# Both components share each node's network namespace. The upstream chart
# assigns 9808 to both, so move only the controller's health endpoint.
health_port = 9810
plugin = next(c for c in pod_spec["containers"] if c["name"] == "ebs-plugin")
healthz = next(p for p in plugin["ports"] if p["name"] == "healthz")
healthz["containerPort"] = health_port
if "hostPort" in healthz:
    healthz["hostPort"] = health_port
probe = next(c for c in pod_spec["containers"] if c["name"] == "liveness-probe")
probe["args"] = [
    arg for arg in probe["args"]
    if not arg.startswith(("--health-port=", "--http-endpoint="))
]
probe["args"].append(f"--http-endpoint=:{health_port}")
yaml.safe_dump_all(documents, sys.stdout, sort_keys=False)
