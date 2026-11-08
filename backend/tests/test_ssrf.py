import socket
import subprocess
import sys
import textwrap
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from app.security import url_guard
from app.security.ip_policy import is_public_ip
from app.security.url_guard import URLRejected, check_dns, resolve_redirects

BACKEND = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("ip,public", [
    ("8.8.8.8", True),
    ("104.244.42.1", True),
    ("2606:4700:4700::1111", True),
    ("127.0.0.1", False),
    ("10.1.2.3", False),
    ("172.16.5.4", False),
    ("192.168.1.1", False),
    ("169.254.169.254", False),        # AWS / GCP / Azure / DigitalOcean metadata
    ("100.100.100.200", False),        # Alibaba Cloud metadata
    ("fd00:ec2::254", False),          # AWS IPv6 metadata
    ("0.0.0.0", False),
    ("::1", False),
    ("::ffff:127.0.0.1", False),       # IPv4-mapped loopback
    ("::ffff:169.254.169.254", False),
    ("64:ff9b::a9fe:a9fe", False),     # NAT64-wrapped metadata address
    ("2002:7f00:1::", False),          # 6to4-wrapped loopback
    ("fe80::1", False),
    ("224.0.0.1", False),
    ("not-an-ip", False),
])
def test_ip_policy(ip, public):
    assert is_public_ip(ip) is public


def _fake_dns(monkeypatch, mapping):
    def fake(host, port, *args, **kwargs):
        if host not in mapping:
            raise socket.gaierror("unknown")
        out = []
        for ip in mapping[host]:
            fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
            out.append((fam, socket.SOCK_STREAM, 6, "", (ip, port)))
        return out

    monkeypatch.setattr(url_guard.socket, "getaddrinfo", fake)


def test_dns_to_private_address_is_blocked(monkeypatch):
    _fake_dns(monkeypatch, {"x.com": ["127.0.0.1"]})
    with pytest.raises(URLRejected) as exc:
        check_dns("x.com")
    assert exc.value.code == "blocked_address"


def test_mixed_public_and_private_answers_are_blocked(monkeypatch):
    _fake_dns(monkeypatch, {"t.co": ["104.244.42.1", "169.254.169.254"]})
    with pytest.raises(URLRejected):
        check_dns("t.co")


def test_public_dns_passes(monkeypatch):
    _fake_dns(monkeypatch, {"t.co": ["2606:4700::1", "104.244.42.1"]})
    assert check_dns("t.co") == ["104.244.42.1", "2606:4700::1"]  # IPv4 first


def test_redirect_to_internal_host_is_blocked(settings, monkeypatch):
    _fake_dns(monkeypatch, {"t.co": ["104.244.42.1"]})
    monkeypatch.setattr(url_guard, "_pinned_request", lambda url, ip, m, t: (301, "http://169.254.169.254/latest"))
    with pytest.raises(URLRejected) as exc:
        resolve_redirects("https://t.co/abc", settings)
    assert exc.value.code == "ip_literal"


def test_redirect_to_unsupported_site_is_blocked(settings, monkeypatch):
    _fake_dns(monkeypatch, {"t.co": ["104.244.42.1"]})
    monkeypatch.setattr(url_guard, "_pinned_request", lambda url, ip, m, t: (302, "https://evil.example/x"))
    with pytest.raises(URLRejected) as exc:
        resolve_redirects("https://t.co/abc", settings)
    assert exc.value.code == "unsupported_site"


def test_redirect_hop_rebinding_to_private_dns_is_blocked(settings, monkeypatch):
    _fake_dns(monkeypatch, {"t.co": ["104.244.42.1"], "vm.tiktok.com": ["10.0.0.5"]})
    monkeypatch.setattr(url_guard, "_pinned_request", lambda url, ip, m, t: (301, "https://vm.tiktok.com/zz"))
    with pytest.raises(URLRejected) as exc:
        resolve_redirects("https://t.co/abc", settings)
    assert exc.value.code == "blocked_address"


def test_shortlink_resolves_to_final_platform_url(settings, monkeypatch):
    _fake_dns(monkeypatch, {"t.co": ["104.244.42.1"]})
    seen = []

    def fake(url, ip, method, timeout):
        seen.append((url, ip))
        return 301, "https://x.com/user/status/1"

    monkeypatch.setattr(url_guard, "_pinned_request", fake)
    assert resolve_redirects("https://t.co/abc", settings) == "https://x.com/user/status/1"
    assert seen == [("https://t.co/abc", "104.244.42.1")]  # request pinned to the checked IP


def test_redirect_loop_is_capped(settings, monkeypatch):
    _fake_dns(monkeypatch, {"t.co": ["104.244.42.1"]})
    monkeypatch.setattr(url_guard, "_pinned_request", lambda url, ip, m, t: (301, "https://t.co/again"))
    with pytest.raises(URLRejected) as exc:
        resolve_redirects("https://t.co/abc", settings)
    assert exc.value.code == "too_many_redirects"


def test_non_shortlink_is_not_fetched(settings, monkeypatch):
    monkeypatch.setattr(url_guard, "_pinned_request", lambda *a: pytest.fail("should not fetch"))
    assert resolve_redirects("https://www.instagram.com/reel/abc/", settings) == "https://www.instagram.com/reel/abc/"


@pytest.fixture
def local_http_server():
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"internal secret")

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv.server_address[1]
    srv.shutdown()


def _run_guarded(code: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", textwrap.dedent(code)], cwd=BACKEND, capture_output=True,
                          text=True, timeout=30)


def test_socket_guard_blocks_dns_rebinding_in_subprocess(local_http_server):
    """Simulate DNS rebinding: a public-looking hostname suddenly resolves to 127.0.0.1.
    The guard checks the address actually being connected to, so the request is refused."""
    port = local_http_server
    proc = _run_guarded(f"""
        import socket, urllib.request
        real = socket.getaddrinfo
        def rebinding(host, *a, **k):
            if host == "x.com":
                return real("127.0.0.1", *a, **k)
            return real(host, *a, **k)
        socket.getaddrinfo = rebinding
        from app.security import net_guard
        net_guard.install()
        try:
            urllib.request.urlopen("http://x.com:{port}/", timeout=5).read()
            print("FETCHED")
        except Exception as e:
            print("BLOCKED", type(e).__name__, e)
    """)
    assert "BLOCKED" in proc.stdout, proc.stdout + proc.stderr
    assert "non-public address 127.0.0.1" in proc.stdout


def test_socket_guard_blocks_direct_ip_and_unix_sockets(local_http_server):
    proc = _run_guarded(f"""
        import socket
        from app.security import net_guard
        net_guard.install()
        for target in [("127.0.0.1", {local_http_server}), ("169.254.169.254", 80)]:
            try:
                socket.create_connection(target, timeout=2); print("CONNECTED")
            except net_guard.BlockedConnectionError:
                print("BLOCKED")
        s = socket.socket(socket.AF_UNIX)
        try:
            s.connect("/var/run/docker.sock"); print("CONNECTED")
        except net_guard.BlockedConnectionError:
            print("BLOCKED")
    """)
    assert proc.stdout.split() == ["BLOCKED", "BLOCKED", "BLOCKED"], proc.stdout + proc.stderr


def test_without_guard_local_server_is_reachable(local_http_server):
    """Control: proves the previous tests fail because of the guard, not the test setup."""
    proc = _run_guarded(f"""
        import urllib.request
        print(urllib.request.urlopen("http://127.0.0.1:{local_http_server}/", timeout=5).read().decode())
    """)
    assert "internal secret" in proc.stdout
