"""Validate EC2 identity before adding provider IDs to kubeadm Nodes."""
import re

from ansible.errors import AnsibleFilterError


def aws_node_provider_ids(nodes, instances):
    if not nodes or len(nodes) != len(instances):
        raise AnsibleFilterError("Registered Nodes and running cluster instances must have matching counts.")
    by_ip = {}
    for instance in instances:
        ip = instance.get("private_ip")
        if not ip or ip in by_ip:
            raise AnsibleFilterError("EC2 private IPs must be present and unique.")
        by_ip[ip] = instance
    result = []
    used_ids = set()
    for node in nodes:
        name = node["metadata"]["name"]
        addresses = [
            address["address"] for address in node.get("status", {}).get("addresses", [])
            if address.get("type") == "InternalIP" and address["address"] in by_ip
        ]
        if len(addresses) != 1:
            raise AnsibleFilterError(f"Node {name} must match exactly one EC2 private IP.")
        instance = by_ip[addresses[0]]
        if instance.get("name") != name:
            raise AnsibleFilterError(f"Node {name} does not match its EC2 Name tag.")
        instance_id = instance.get("id", "")
        az = instance.get("az", "")
        if not re.fullmatch(r"i-[0-9a-f]{8,17}", instance_id) or not az:
            raise AnsibleFilterError(f"Invalid EC2 identity for Node {name}.")
        if instance_id in used_ids:
            raise AnsibleFilterError("Multiple Nodes matched the same EC2 instance.")
        used_ids.add(instance_id)
        expected = f"aws:///{az}/{instance_id}"
        current = node.get("spec", {}).get("providerID", "")
        if current and current != expected:
            raise AnsibleFilterError(f"Node {name} already has a different providerID; inspect it before proceeding.")
        result.append({"name": name, "provider_id": expected})
    return result


class FilterModule:
    def filters(self):
        return {"aws_node_provider_ids": aws_node_provider_ids}
