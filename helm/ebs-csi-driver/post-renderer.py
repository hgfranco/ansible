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
yaml.safe_dump_all(documents, sys.stdout, sort_keys=False)
