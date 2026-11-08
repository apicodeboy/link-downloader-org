"""Socket-level SSRF guard (layer 3) for the yt-dlp subprocess.

yt-dlp makes many requests of its own (APIs, CDNs, manifests). Instead of trusting every
URL it discovers, this module patches `socket.socket.connect` so that *every* TCP
connection is checked against the IP policy at connect time, using the address actually
being connected to. Because the check happens on the final IP, DNS rebinding cannot slip
past it. Unix sockets are blocked too.

Only install this in a dedicated process (the yt-dlp runner): it would also block
connections to Redis or a local database.
"""
from __future__ import annotations

import ipaddress
import socket

from .ip_policy import is_public_ip


class BlockedConnectionError(ConnectionRefusedError):
    pass


_installed = False


def _check(sock: socket.socket, address):
    family = sock.family
    if family == getattr(socket, "AF_UNIX", None):
        raise BlockedConnectionError("Blocked: unix socket connections are not allowed")
    if family not in (socket.AF_INET, socket.AF_INET6):
        raise BlockedConnectionError(f"Blocked: socket family {family} is not allowed")
    host, port = address[0], address[1]
    try:
        ipaddress.ip_address(str(host).split("%", 1)[0])
        candidates = [str(host)]
        resolved = False
    except ValueError:
        infos = socket.getaddrinfo(host, port, family, socket.SOCK_STREAM)
        candidates = [info[4][0] for info in infos]
        resolved = True
    for ip in candidates:
        if not is_public_ip(ip):
            raise BlockedConnectionError(f"Blocked connection to non-public address {ip}")
    if resolved:
        return (candidates[0], port) + tuple(address[2:])
    return address


def install() -> None:
    global _installed
    if _installed:
        return
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def connect(self, address):
        return original_connect(self, _check(self, address))

    def connect_ex(self, address):
        return original_connect_ex(self, _check(self, address))

    socket.socket.connect = connect  # type: ignore[method-assign]
    socket.socket.connect_ex = connect_ex  # type: ignore[method-assign]
    _installed = True
