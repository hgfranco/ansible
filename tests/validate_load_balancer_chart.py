"""Check the actual rendered controller Deployment for this kubeadm setup."""
import sys

import yaml


def validate(path):
    with open(path, encoding="utf-8") as stream:
        documents = list(yaml.safe_load_all(stream))
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
        "--aws-vpc-id=vpc-0123456789abcdef0", "--default-target-type=instance",
        "--enable-shield=false", "--enable-waf=false", "--enable-wafv2=false",
    ]:
        assert argument in args, (argument, args)
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
