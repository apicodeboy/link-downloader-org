"""Which IP addresses the server is allowed to connect to on a user's behalf."""
from __future__ import annotations

import ipaddress
from ipaddress import IPv4Address, IPv6Address

IPAddress = IPv4Address | IPv6Address

# Ranges that are blocked even if Python's `is_global` would allow them, plus explicit
# cloud metadata endpoints for defence in depth.
_EXTRA_BLOCKED = [
    ipaddress.ip_network(n)
    for n in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",       # carrier-grade NAT; includes Alibaba metadata 100.100.100.200
        "127.0.0.0/8",
        "169.254.0.0/16",      # link-local; includes AWS/GCP/Azure/DO/Hostinger metadata 169.254.169.254
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.0.2.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "224.0.0.0/4",
        "240.0.0.0/4",
        "255.255.255.255/32",
        "::/128",
        "::1/128",
        "fc00::/7",            # unique local; includes AWS IPv6 metadata fd00:ec2::254
        "fe80::/10",
        "ff00::/8",
        "2001:db8::/32",
    )
]
_NAT64 = ipaddress.ip_network("64:ff9b::/96")


def _embedded_ipv4(ip: IPv6Address) -> IPv4Address | None:
    if ip.ipv4_mapped:
        return ip.ipv4_mapped
    if ip.sixtofour:
        return ip.sixtofour
    if ip.teredo:
        return ip.teredo[1]
    if ip in _NAT64:
        return IPv4Address(int(ip) & 0xFFFFFFFF)
    return None


def is_public_ip(ip: IPAddress | str) -> bool:
    """True only for globally routable unicast addresses."""
    if isinstance(ip, str):
        try:
            ip = ipaddress.ip_address(ip.split("%", 1)[0])
        except ValueError:
            return False
    if isinstance(ip, IPv6Address):
        embedded = _embedded_ipv4(ip)
        if embedded is not None:
            return is_public_ip(embedded)
    if any(ip in net for net in _EXTRA_BLOCKED if net.version == ip.version):
        return False
    if ip.is_multicast or ip.is_reserved or ip.is_loopback or ip.is_link_local or ip.is_private:
        return False
    return ip.is_global
