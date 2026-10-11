"""Check the actual rendered controller Deployment for this kubeadm setup."""
import sys

import yaml


def validate(path):
    with open(path, encoding="utf-8") as stream:
        rendered = list(yaml.safe_load_all(stream))
    # Helm emits IngressClass and its parameters inside a Kubernetes List.
    documents = []
    for document in rendered:
        if document and document.get("kind") == "List":
            documents.extend(document.get("items", []))
        elif document:
            documents.append(document)
    deployments = [
        document for document in documents
        if document and document.get("kind") == "Deployment"
        and document["metadata"]["name"] == "aws-load-balancer-controller"
    ]
    assert len(deployments) == 1, "Expected exactly one controller Deployment"
    deployment = deployments[0]
    spec = deployment["spec"]
    pod = spec["template"]["spec"]
    assert spec["replicas"] == 2
    assert pod["hostNetwork"] is True
    assert pod["dnsPolicy"] == "ClusterFirstWithHostNet"
    assert pod["affinity"]["podAntiAffinity"]["requiredDuringSchedulingIgnoredDuringExecution"]
    containers = pod["containers"]
    assert len(containers) == 1
    controller = containers[0]
    assert controller["image"].endswith(":v3.6.0"), controller["image"]
    args = controller["args"]
    for argument in [
        "--cluster-name=kubernetes", "--aws-region=us-east-1",
        "--aws-vpc-id=vpc-0123456789abcdef0",
        "--enable-shield=false", "--enable-waf=false", "--enable-wafv2=false",
    ]:
        assert argument in args, (argument, args)
    # The official chart omits the flag for the controller default, instance.
    target_args = [arg for arg in args if arg.startswith("--default-target-type=")]
    assert target_args in ([], ["--default-target-type=instance"]), target_args
    assert controller["resources"]["requests"]["memory"] == "128Mi"
    for container in containers:
        for env in container.get("env", []):
            assert env["name"] not in {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"}
    services = [
        document for document in documents
        if document and document.get("kind") == "Service"
    ]
    assert all(service["spec"].get("type", "ClusterIP") != "LoadBalancer" for service in services)
    assert any(
        document and document.get("kind") == "IngressClass"
        and document["metadata"]["name"] == "alb"
        for document in documents
    )


if __name__ == "__main__":
    validate(sys.argv[1])
