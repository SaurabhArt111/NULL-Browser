"""Built-in VPN: sends all browser traffic through a proxy server of your choice (SOCKS5, HTTP or HTTPS).

What this is - and is not. It is a tunnel for *this browser's* traffic: web pages, downloads, WebSockets, and DNS lookups
(a SOCKS5 / CONNECT proxy resolves the host names itself, so your local resolver is never asked). It is not a system-wide
VPN and it does not provide servers: you add the endpoint your VPN provider (or your own server, Tor, ``ssh -D``) gives you.

How it is wired. Chromium reads its proxy once, when the engine starts, so the proxy is passed on the command line
(`engine/flags.py` calls `chromium_args()` below) and switching the VPN on or off restarts the browser (tabs come back).
With an explicit proxy Chromium never falls back to a direct connection: if the proxy is down, pages fail to load instead of
leaking your address. That is the kill switch, and it cannot be bypassed by a page.

Chromium cannot log in to a SOCKS5 proxy (no username / password for SOCKS), so authenticated servers must be HTTP / HTTPS
proxies; their credentials are answered by `Tab.on_proxy_auth`. Credentials live in vpn.json (owner-only permissions).
"""
import json
import logging
import os
import secrets
import socket
import ssl
import struct
import time

log = logging.getLogger("null.vpn")
SCHEMES = ("socks5", "http", "https")
TEST_HOST = "example.com"


class VpnError(ValueError):
    pass


def _path(data_dir):
    return os.path.join(data_dir, "vpn.json")


def load_raw(data_dir):
    try:
        with open(_path(data_dir), encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            return {"enabled": bool(d.get("enabled")), "active": str(d.get("active") or ""),
                    "servers": [s for s in d.get("servers", []) if isinstance(s, dict) and s.get("host")]}
    except (OSError, ValueError):
        pass
    return {"enabled": False, "active": "", "servers": []}


def chromium_args(data_dir):
    """Command-line switches for the saved state (plain file IO: runs before Qt exists). [] when the VPN is off."""
    d = load_raw(data_dir)
    if not d["enabled"]:
        return []
    s = next((x for x in d["servers"] if x.get("id") == d["active"]), None)
    if s is None:
        return []
    host = s["host"] if ":" not in s["host"] else f"[{s['host']}]"
    return [f"--proxy-server={s['scheme']}://{host}:{int(s['port'])}",
            "--proxy-bypass-list=localhost;127.0.0.1;[::1]",                    # the local Null Search engine must stay reachable
            "--force-webrtc-ip-handling-policy=disable_non_proxied_udp"]


class VpnStore:
    def __init__(self, data_dir):
        self.dir = data_dir
        self.state = load_raw(data_dir)

    # ---- persistence --------------------------------------------------------------------------
    def save(self):
        tmp = _path(self.dir) + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2)
        os.replace(tmp, _path(self.dir))
        try:
            os.chmod(_path(self.dir), 0o600)
        except OSError:
            pass

    # ---- queries ------------------------------------------------------------------------------
    @property
    def enabled(self):
        return bool(self.state["enabled"] and self.active())

    def active(self):
        return next((s for s in self.state["servers"] if s["id"] == self.state["active"]), None)

    def get(self, sid):
        return next((s for s in self.state["servers"] if s["id"] == sid), None)

    def public(self):
        """What the settings page sees: everything except the password."""
        out = []
        for s in self.state["servers"]:
            c = {k: v for k, v in s.items() if k != "password"}
            c["has_password"] = bool(s.get("password"))
            out.append(c)
        return {"enabled": self.enabled, "active": self.state["active"], "servers": out}

    def credentials_for(self, host, port=None):
        """(user, password) for the active proxy when `host` is its address, else None."""
        s = self.active()
        if s and self.state["enabled"] and s.get("user") and s["host"].lower() == (host or "").lower() and (port is None or int(port) == int(s["port"])):
            return s["user"], s.get("password", "")
        return None

    # ---- changes ------------------------------------------------------------------------------
    def upsert(self, data):
        scheme = str(data.get("scheme") or "socks5").lower()
        host = str(data.get("host") or "").strip().strip("[]")
        try:
            port = int(data.get("port"))
        except (TypeError, ValueError):
            raise VpnError("Enter a port number.")
        if scheme not in SCHEMES:
            raise VpnError("Type must be SOCKS5, HTTP or HTTPS.")
        if not host or any(c in host for c in " /\\@?#") or not (0 < port < 65536):
            raise VpnError("Enter a valid server address and port.")
        user = str(data.get("user") or "")
        sid = str(data.get("id") or "")
        old = self.get(sid) if sid else None
        password = data.get("password")
        if password is None:
            password = (old or {}).get("password", "")
        if scheme == "socks5" and user:
            raise VpnError("Chromium cannot sign in to a SOCKS5 proxy. Use an HTTP / HTTPS proxy for servers that need a username, "
                           "or a SOCKS5 endpoint that needs none (Tor, `ssh -D`, a VPN client's local proxy).")
        rec = {"id": sid or secrets.token_hex(4), "name": str(data.get("name") or f"{host}:{port}")[:60], "scheme": scheme,
               "host": host, "port": port, "user": user, "password": password if user else ""}
        if old:
            self.state["servers"][self.state["servers"].index(old)] = rec
        else:
            self.state["servers"].append(rec)
        if not self.state["active"]:
            self.state["active"] = rec["id"]
        self.save()
        return rec["id"]

    def delete(self, sid):
        self.state["servers"] = [s for s in self.state["servers"] if s["id"] != sid]
        if self.state["active"] == sid:
            self.state["active"] = self.state["servers"][0]["id"] if self.state["servers"] else ""
            self.state["enabled"] = self.state["enabled"] and bool(self.state["active"])
        self.save()

    def set_active(self, sid):
        if self.get(sid) is None:
            raise VpnError("Unknown server.")
        self.state["active"] = sid
        self.save()

    def set_enabled(self, on):
        if on and not self.active():
            raise VpnError("Add a server first, then turn the VPN on.")
        self.state["enabled"] = bool(on)
        self.save()


# ---- connection test (no third party involved: the proxy is asked to open a connection to example.com:443) --------------
def _recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        part = sock.recv(n - len(buf))
        if not part:
            raise VpnError("The server closed the connection.")
        buf += part
    return buf


def test_server(s, timeout=8.0):
    """Open a tunnel through the proxy to example.com:443. Returns {"ok", "ms", "message"}; never raises."""
    t0 = time.time()
    try:
        raw = socket.create_connection((s["host"], int(s["port"])), timeout=timeout)
    except OSError as exc:
        return {"ok": False, "ms": 0, "message": f"Cannot reach {s['host']}:{s['port']} ({exc.strerror or exc})."}
    try:
        raw.settimeout(timeout)
        sock = raw
        if s["scheme"] == "https":
            sock = ssl.create_default_context().wrap_socket(raw, server_hostname=s["host"])
        if s["scheme"] == "socks5":
            sock.sendall(b"\x05\x01\x00")
            if _recv_exact(sock, 2) != b"\x05\x00":
                raise VpnError("The SOCKS5 server wants a login, which Chromium does not support.")
            host = TEST_HOST.encode()
            sock.sendall(b"\x05\x01\x00\x03" + bytes([len(host)]) + host + struct.pack(">H", 443))
            head = _recv_exact(sock, 4)
            if head[1] != 0:
                raise VpnError(f"The SOCKS5 server refused the connection (code {head[1]}).")
        else:
            lines = [f"CONNECT {TEST_HOST}:443 HTTP/1.1", f"Host: {TEST_HOST}:443"]
            if s.get("user"):
                import base64
                token = base64.b64encode(f"{s['user']}:{s.get('password', '')}".encode()).decode()
                lines.append(f"Proxy-Authorization: Basic {token}")
            sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
            status = b""
            while b"\r\n" not in status and len(status) < 1024:
                chunk = sock.recv(256)
                if not chunk:
                    break
                status += chunk
            code = status.split(b" ")[1] if status.startswith(b"HTTP/") and b" " in status else b"?"
            if code == b"407":
                raise VpnError("The proxy rejected the username or password.")
            if code != b"200":
                raise VpnError(f"The proxy answered {code.decode('ascii', 'replace')} instead of opening a tunnel.")
        return {"ok": True, "ms": int((time.time() - t0) * 1000), "message": "Connected."}
    except VpnError as exc:
        return {"ok": False, "ms": 0, "message": str(exc)}
    except (OSError, ssl.SSLError) as exc:
        return {"ok": False, "ms": 0, "message": f"Connection failed ({getattr(exc, 'strerror', None) or exc})."}
    finally:
        try:
            raw.close()
        except OSError:
            pass
