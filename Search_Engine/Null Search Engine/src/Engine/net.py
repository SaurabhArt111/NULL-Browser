"""SSRF-safe URL handling and fetching.

Everything the engine fetches on behalf of a *user-supplied* URL (crawl seeds, discovered links, proxied
images, favicons) goes through :func:`safe_get`. It only speaks http(s), refuses loopback / private /
link-local / reserved addresses (also for every redirect hop), limits ports, redirects and body size.

Known limit: the address is validated right before the request, not pinned for the connection itself, so a
hostile DNS server could in theory flip the answer in between (DNS rebinding). The crawler therefore also
runs only on explicit user action, and the server only ever listens on loopback.
"""
from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Dict, Iterable, List, Optional
from urllib.parse import parse_qsl, quote, unquote, urlencode, urljoin, urlsplit, urlunsplit

import httpx

ALLOWED_PORTS = {None, 80, 443, 8080, 8443}
TRACKING_PARAMS = re.compile(r"^(utm_.*|fbclid|gclid|dclid|msclkid|mc_eid|mc_cid|igshid|yclid|_hsenc|_hsmi|ref_src|spm|cmpid)$", re.I)
USER_AGENT = "Mozilla/5.0 (compatible; NullSearch/1.0; +local personal search engine)"

Resolver = Callable[[str, int], Awaitable[List[str]]]


class UnsafeURL(ValueError):
    pass


class FetchError(Exception):
    pass


def is_public_ip(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    if isinstance(a, ipaddress.IPv6Address) and a.ipv4_mapped:
        a = a.ipv4_mapped
    return a.is_global and not (a.is_multicast or a.is_private or a.is_loopback or a.is_link_local or a.is_reserved or a.is_unspecified)


async def default_resolver(host: str, port: int) -> List[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({i[4][0] for i in infos})


def normalize_url(url: str, base: Optional[str] = None) -> Optional[str]:
    """Canonical form used as the index key: lowercase host, no fragment/default port/tracking params."""
    try:
        if base:
            url = urljoin(base, url)
        p = urlsplit(url.strip())
    except ValueError:
        return None
    if p.scheme not in ("http", "https") or not p.hostname:
        return None
    try:
        port = p.port
    except ValueError:
        return None
    host = p.hostname.lower().rstrip(".")
    if ":" in host:
        host = f"[{host}]"
    default = 80 if p.scheme == "http" else 443
    netloc = host if port in (None, default) else f"{host}:{port}"
    if p.username or p.password:
        return None                                              # never index or fetch URLs with embedded credentials
    query = urlencode([(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not TRACKING_PARAMS.match(k)])
    path = quote(unquote(p.path), safe="/:@!$&'()*+,;=-._~%") or "/"
    return urlunsplit((p.scheme, netloc, path, query, ""))


def dedupe_key(url: str) -> str:
    """Looser identity for merging search results: ignores scheme, ``www.`` and trailing slashes."""
    n = normalize_url(url) or url
    p = urlsplit(n)
    host = (p.hostname or "")
    host = host[4:] if host.startswith("www.") else host
    return host + (f":{p.port}" if p.port and p.port not in (80, 443) else "") + p.path.rstrip("/") + ("?" + p.query if p.query else "")


async def check_url(url: str, allow_private: bool = False, resolver: Optional[Resolver] = None) -> str:
    """Validate ``url`` and return its normalised form, or raise :class:`UnsafeURL`."""
    n = normalize_url(url)
    if not n:
        raise UnsafeURL("Only plain http(s) URLs are allowed")
    p = urlsplit(n)
    if not allow_private and p.port not in ALLOWED_PORTS:
        raise UnsafeURL("Port not allowed")
    host = p.hostname or ""
    if not allow_private and (host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".lan", ".home"))):
        raise UnsafeURL("Local hostnames are not allowed")
    try:
        ipaddress.ip_address(host.strip("[]"))
        addrs = [host.strip("[]")]
    except ValueError:
        try:
            addrs = await (resolver or default_resolver)(host, p.port or (443 if p.scheme == "https" else 80))
        except (OSError, UnicodeError):
            raise UnsafeURL("Host could not be resolved")
    if not addrs:
        raise UnsafeURL("Host could not be resolved")
    if not allow_private and not all(is_public_ip(a) for a in addrs):
        raise UnsafeURL("Address is not on the public internet")
    return n


@dataclass
class Fetched:
    url: str
    status: int
    headers: Dict[str, str]
    body: bytes
    truncated: bool = False

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "").split(";")[0].strip().lower()


async def safe_get(client: httpx.AsyncClient, url: str, *, max_bytes: int = 2_000_000, allow_private: bool = False,
                   max_redirects: int = 5, headers: Optional[Dict[str, str]] = None, timeout: float = 10.0,
                   accept_types: Optional[Iterable[str]] = None, resolver: Optional[Resolver] = None) -> Fetched:
    """GET with SSRF checks on every hop and a hard cap on the body size.

    ``accept_types`` (e.g. ``("text/html",)``): the body is not downloaded for other content types.
    """
    hdrs = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate", **(headers or {})}
    cur = await check_url(url, allow_private, resolver)
    for _ in range(max_redirects + 1):
        try:
            async with client.stream("GET", cur, headers=hdrs, timeout=timeout, follow_redirects=False) as r:
                if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                    nxt = normalize_url(r.headers["location"], base=cur)
                    if not nxt:
                        raise FetchError("Bad redirect")
                    cur = await check_url(nxt, allow_private, resolver)
                    continue
                ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
                hdr = {k.lower(): v for k, v in r.headers.items()}
                if accept_types is not None and ctype not in set(accept_types):
                    return Fetched(cur, r.status_code, hdr, b"", False)
                try:
                    declared = int(r.headers.get("content-length", "0"))
                except ValueError:
                    declared = 0
                if declared > max_bytes * 4:
                    return Fetched(cur, r.status_code, hdr, b"", True)
                buf, truncated = bytearray(), False
                async for chunk in r.aiter_bytes():
                    buf += chunk
                    if len(buf) > max_bytes:
                        del buf[max_bytes:]
                        truncated = True
                        break
                return Fetched(cur, r.status_code, hdr, bytes(buf), truncated)
        except httpx.HTTPError as e:
            raise FetchError(type(e).__name__) from e
    raise FetchError("Too many redirects")
