"""Qt side of the built-in VPN: Qt's own network code (favicons, avatar, update checks, downloads of icons...) must use the same
tunnel as the web pages, otherwise it would reveal the real address. Chromium itself is handled by command-line flags
(core/vpn.py); this covers everything else that lives in the Qt process."""
import ipaddress

from PyQt6.QtNetwork import QNetworkProxy, QNetworkProxyFactory, QNetworkProxyQuery

LOOPBACK = {"localhost", "127.0.0.1", "::1", ""}


def is_loopback(host):
    h = (host or "").strip("[]").lower()
    if h in LOOPBACK:
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


class VpnProxyFactory(QNetworkProxyFactory):
    def __init__(self, server):
        super().__init__()
        kind = QNetworkProxy.ProxyType.Socks5Proxy if server["scheme"] == "socks5" else QNetworkProxy.ProxyType.HttpProxy
        self.proxy = QNetworkProxy(kind, server["host"], int(server["port"]), server.get("user", ""), server.get("password", ""))
        self.direct = QNetworkProxy(QNetworkProxy.ProxyType.NoProxy)

    def queryProxy(self, query=QNetworkProxyQuery()):
        return [self.direct if is_loopback(query.peerHostName()) else self.proxy]


_factory = None


def apply(store):
    """Install (or remove) the application-wide proxy for Qt's own sockets according to the VPN state."""
    global _factory
    if store.enabled:
        _factory = VpnProxyFactory(store.active())
        QNetworkProxyFactory.setApplicationProxyFactory(_factory)
    else:
        _factory = None
        QNetworkProxyFactory.setApplicationProxyFactory(None)
        QNetworkProxy.setApplicationProxy(QNetworkProxy(QNetworkProxy.ProxyType.NoProxy))


def urllib_opener(store, *handlers):
    """urllib opener that goes through the tunnel (HTTP / HTTPS proxies only: urllib has no SOCKS). A direct opener when the VPN is off.
    Raises VpnError-like RuntimeError for SOCKS so callers refuse the request instead of leaking."""
    import urllib.request
    if not store.enabled:
        return urllib.request.build_opener(*handlers)
    s = store.active()
    if s["scheme"] == "socks5":
        raise RuntimeError("blocked: this request cannot use the SOCKS5 tunnel")
    auth = f"{s['user']}:{s.get('password', '')}@" if s.get("user") else ""
    url = f"{s['scheme']}://{auth}{s['host']}:{s['port']}"
    return urllib.request.build_opener(urllib.request.ProxyHandler({"http": url, "https": url}), *handlers)
