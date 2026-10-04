"""Validate IPv4 cluster networks without extra Python dependencies."""
from ipaddress import ip_address, ip_network


def kubeadm_networks_valid(values):
    try:
        networks = [ip_network(value, strict=True) for value in values]
        return len(networks) == 3 and all(net.version == 4 for net in networks) and all(
            not a.overlaps(b)
            for index, a in enumerate(networks)
            for b in networks[index + 1:]
        )
    except (TypeError, ValueError):
        return False


def kubeadm_address_in_network(address, cidr):
    try:
        ip = ip_address(address)
        network = ip_network(cidr, strict=True)
        return ip.version == network.version == 4 and ip in network
    except (TypeError, ValueError):
        return False


class FilterModule:
    def filters(self):
        return {
            "kubeadm_networks_valid": kubeadm_networks_valid,
            "kubeadm_address_in_network": kubeadm_address_in_network,
        }
