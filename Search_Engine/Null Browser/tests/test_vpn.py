import base64
import json
import os
import socket
import socketserver
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from null_browser.core import vpn  # noqa: E402


def serve(handler):
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class Socks(socketserver.BaseRequestHandler):
    def handle(self):
        s = self.request
        assert s.recv(3) == b"\x05\x01\x00"
        s.sendall(b"\x05\x00")
        head = s.recv(4)
        n = s.recv(1)[0]
        host = s.recv(n)
        s.recv(2)
        ok = host == b"example.com" and head[:2] == b"\x05\x01"
        s.sendall(b"\x05" + (b"\x00" if ok else b"\x05") + b"\x00\x01\x00\x00\x00\x00\x00\x00")


class HttpConnect(socketserver.BaseRequestHandler):
    user, password = "bob", "pw"

    def handle(self):
        data = b""
        while b"\r\n\r\n" not in data:
            data += self.request.recv(1024)
        want = "Basic " + base64.b64encode(f"{self.user}:{self.password}".encode()).decode()
        if f"Proxy-Authorization: {want}" in data.decode():
            self.request.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
        else:
            self.request.sendall(b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\n")


class VpnStoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.store = vpn.VpnStore(self.dir)

    def test_off_by_default_no_flags(self):
        self.assertEqual(vpn.chromium_args(self.dir), [])
        self.assertFalse(self.store.enabled)

    def test_enable_needs_a_server(self):
        with self.assertRaises(vpn.VpnError):
            self.store.set_enabled(True)

    def test_flags_when_on(self):
        sid = self.store.upsert({"name": "t", "scheme": "socks5", "host": "127.0.0.1", "port": 9050})
        self.store.set_enabled(True)
        flags = vpn.chromium_args(self.dir)
        self.assertIn("--proxy-server=socks5://127.0.0.1:9050", flags)
        self.assertIn("--force-webrtc-ip-handling-policy=disable_non_proxied_udp", flags)
        self.assertTrue(any(f.startswith("--proxy-bypass-list=") and "127.0.0.1" in f for f in flags))
        self.store.set_enabled(False)
        self.assertEqual(vpn.chromium_args(self.dir), [])
        self.assertEqual(self.store.active()["id"], sid)

    def test_socks5_login_is_refused_with_a_reason(self):
        with self.assertRaises(vpn.VpnError) as cm:
            self.store.upsert({"scheme": "socks5", "host": "h", "port": 1, "user": "u", "password": "p"})
        self.assertIn("SOCKS5", str(cm.exception))

    def test_bad_input(self):
        for bad in ({"host": "", "port": 80}, {"host": "a b", "port": 80}, {"host": "a", "port": 0}, {"host": "a", "port": "x"},
                    {"host": "a", "port": 1, "scheme": "ftp"}, {"host": "a/b", "port": 1}):
            with self.assertRaises(vpn.VpnError, msg=str(bad)):
                self.store.upsert(bad)

    def test_password_never_leaves_public_view_and_is_kept_on_edit(self):
        sid = self.store.upsert({"scheme": "http", "host": "p.example", "port": 8080, "user": "bob", "password": "secret"})
        self.assertNotIn("secret", json.dumps(self.store.public()))
        self.assertTrue(self.store.public()["servers"][0]["has_password"])
        self.store.upsert({"id": sid, "scheme": "http", "host": "p.example", "port": 8081, "user": "bob"})    # no password field: keep it
        self.assertEqual(self.store.get(sid)["password"], "secret")
        self.assertEqual(self.store.get(sid)["port"], 8081)

    def test_file_is_private(self):
        self.store.upsert({"scheme": "http", "host": "p.example", "port": 8080, "user": "bob", "password": "secret"})
        if os.name == "posix":
            self.assertEqual(os.stat(os.path.join(self.dir, "vpn.json")).st_mode & 0o077, 0)

    def test_credentials_only_for_the_active_proxy(self):
        self.store.upsert({"scheme": "http", "host": "p.example", "port": 8080, "user": "bob", "password": "secret"})
        self.assertIsNone(self.store.credentials_for("p.example"))             # VPN not enabled yet
        self.store.set_enabled(True)
        self.assertEqual(self.store.credentials_for("P.example"), ("bob", "secret"))
        self.assertIsNone(self.store.credentials_for("evil.example"))

    def test_delete_active_turns_vpn_off(self):
        sid = self.store.upsert({"scheme": "socks5", "host": "h", "port": 1})
        self.store.set_enabled(True)
        self.store.delete(sid)
        self.assertFalse(self.store.enabled)
        self.assertEqual(vpn.chromium_args(self.dir), [])


class ConnectionTests(unittest.TestCase):
    def test_socks5_ok(self):
        srv = serve(Socks)
        r = vpn.test_server({"scheme": "socks5", "host": "127.0.0.1", "port": srv.server_address[1]}, timeout=3)
        srv.shutdown()
        self.assertTrue(r["ok"], r)

    def test_http_connect_ok_and_bad_password(self):
        srv = serve(HttpConnect)
        port = srv.server_address[1]
        good = vpn.test_server({"scheme": "http", "host": "127.0.0.1", "port": port, "user": "bob", "password": "pw"}, timeout=3)
        bad = vpn.test_server({"scheme": "http", "host": "127.0.0.1", "port": port, "user": "bob", "password": "nope"}, timeout=3)
        srv.shutdown()
        self.assertTrue(good["ok"], good)
        self.assertFalse(bad["ok"])
        self.assertIn("username or password", bad["message"])

    def test_unreachable(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        r = vpn.test_server({"scheme": "socks5", "host": "127.0.0.1", "port": port}, timeout=2)
        self.assertFalse(r["ok"])
        self.assertIn("Cannot reach", r["message"])


if __name__ == "__main__":
    unittest.main()
