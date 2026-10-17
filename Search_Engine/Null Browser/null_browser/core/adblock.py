"""Request interceptor: ad / tracker blocking, DNT + Global Privacy Control headers.

Matching is done by a real filter engine (Brave's adblock-rust through `adblockengine.FilterManager`; see that module for the
fallbacks). While the engine is still building (first start: well under a second with the Rust engine) the small built-in
domain list in data/blocklist.txt protects the page, so there is never an unprotected window.

`interceptRequest` runs on Chromium's IO thread: it never touches widgets, only reads plain attributes, and never raises.
"""
import base64
import hashlib
import json
import logging
import os
import re
from collections import Counter

from PyQt6.QtCore import QUrl, pyqtSignal
from PyQt6.QtWebEngineCore import QWebEngineUrlRequestInterceptor, QWebEngineUrlRequestInfo

from . import paths
from .adblockengine import FilterManager

log = logging.getLogger("null.adblock")
LIST_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "blocklist.txt")
RT = QWebEngineUrlRequestInfo.ResourceType
FULL = QUrl.ComponentFormattingOption.FullyEncoded

# Qt resource type -> Adblock Plus request type
_TYPES = {}
for _qt, _abp in (("MainFrame", "document"), ("SubFrame", "subdocument"), ("Stylesheet", "stylesheet"), ("Script", "script"),
                  ("Image", "image"), ("FontResource", "font"), ("SubResource", "other"), ("Object", "object"), ("Media", "media"),
                  ("Worker", "other"), ("SharedWorker", "other"), ("Prefetch", "other"), ("Favicon", "image"), ("Xhr", "xmlhttprequest"),
                  ("Ping", "ping"), ("ServiceWorker", "other"), ("CspReport", "csp_report"), ("PluginResource", "object"),
                  ("NavigationPreloadMainFrame", "document"), ("NavigationPreloadSubFrame", "subdocument"), ("Unknown", "other")):
    _member = getattr(RT, "ResourceType" + _qt, None)
    if _member is not None:
        _TYPES[_member] = _abp

_DOMAIN = re.compile(r"^[a-z0-9][a-z0-9.-]*\.[a-z0-9-]+$")
CACHE_MAX = 20000


def _host_in(host, domains):
    """True if host or any parent domain is in the set."""
    while host:
        if host in domains:
            return True
        i = host.find(".")
        if i < 0:
            return False
        host = host[i + 1:]
    return False


def _registrable(host):
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


class AdBlocker(QWebEngineUrlRequestInterceptor):
    blocked = pyqtSignal(str)          # emits the top-level host a block belongs to

    def __init__(self, settings, perms=None, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.perms = perms
        self.ads, self.trackers = set(), set()             # built-in domain lists: used until the engine is ready
        self.custom_lines = []                             # user rules, any filter syntax
        self.custom = set()                                # the domain-only subset (for the legacy matcher / settings list)
        self.allowlist = set()
        self.site_allow = set()
        self.safe_mode = False
        self.total = 0
        self.redirected = 0
        self.per_site = Counter()
        self.enabled = True
        self.block_trackers = True
        self.send_dnt = True
        self._cache = {}
        self._stubs = {}                                   # id -> (mime, bytes): harmless replacements served at null://stub/<id>
        self.filters = FilterManager(settings, self)
        self.filters.ready.connect(lambda _label: self._cache.clear())
        self.cosmetic = None                               # set by app: core.cosmetic.CosmeticFilter
        self.load_lists()
        self.refresh()

    # ---- lifecycle -------------------------------------------------------------------------------
    def start(self):
        """Begin building the engine (call once the event loop is about to run)."""
        self.filters.set_custom(self._custom_filter_text())
        self.filters.rebuild()

    def refresh(self):
        self.enabled = bool(self.settings.get("adblock")) and not self.safe_mode
        if self.perms is not None and self.perms.default("intrusive_ads") == "allow":
            self.enabled = False
        self.site_allow = set()
        if self.perms is not None:
            for (origin, feat), val in list(self.perms.cache.items()):
                if feat == "intrusive_ads" and val == "allow":
                    self.site_allow.add(origin.split("://", 1)[-1].split(":")[0].lower())
        trackers = bool(self.settings.get("block_trackers"))
        if trackers != self.block_trackers and hasattr(self, "filters"):
            self.block_trackers = trackers
            if self.filters.backend is not None:
                self.filters.rebuild()                     # tracker lists are added / dropped
        self.block_trackers = trackers
        self.send_dnt = bool(self.settings.get("send_dnt"))
        self._cache.clear()

    @property
    def backend_label(self):
        b = self.filters.backend
        return b.label if b else "starting"

    # ---- lists and user rules ----------------------------------------------------------------------
    def _custom_path(self):
        return os.path.join(paths.data_dir(), "adblock-custom.json")

    def load_lists(self):
        ads, trackers = set(), set()
        try:
            with open(LIST_FILE, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or (line.startswith("#") and not line.startswith("##")):
                        continue
                    if line.startswith("##"):
                        d = line[2:].strip().split("/")[0]
                        if d:
                            trackers.add(d.lower())
                    else:
                        ads.add(line.split("/")[0].lower())
        except OSError:
            log.warning("blocklist.txt not found; ad blocking limited to the filter lists")
        self.ads, self.trackers = ads, trackers
        try:
            with open(self._custom_path(), encoding="utf-8") as f:
                d = json.load(f)
            self.custom_lines = [x for x in d.get("rules", []) if isinstance(x, str)]
            self.allowlist = {x.lower() for x in d.get("allow", []) if isinstance(x, str)}
        except (OSError, ValueError):
            self.custom_lines, self.allowlist = [], set()
        self._sync_custom()

    def _sync_custom(self):
        self.custom = {r[2:].rstrip("^").lower() for r in self.custom_lines if r.startswith("||") and r.endswith("^") and _DOMAIN.match(r[2:-1].lower())}

    def _custom_filter_text(self):
        return "\n".join(self.custom_lines)

    def save_custom(self):
        try:
            with open(self._custom_path(), "w", encoding="utf-8") as f:
                json.dump({"rules": self.custom_lines, "allow": sorted(self.allowlist)}, f, indent=2)
        except OSError:
            log.exception("could not save custom adblock rules")
        self.filters.set_custom(self._custom_filter_text())

    @staticmethod
    def parse_rule(text):
        """Accepts a domain (`ads.example.com`), or any Adblock Plus / uBlock Origin filter. Returns the normalised rule or ''."""
        t = (text or "").strip()
        if not t or len(t) > 500 or "\n" in t or t.startswith("!"):
            return ""
        low = t.lower()
        if low.startswith(("http://", "https://")):
            low = low.split("://", 1)[1].split("/")[0].split(":")[0]
            t = low
        if _DOMAIN.match(low) and " " not in low:
            return "||" + low.strip(".") + "^"
        if low.startswith("||") and "^" not in low and "/" not in low and "$" not in low and _DOMAIN.match(low[2:]):
            return low + "^"
        if t.startswith(("||", "|", "@@", "/")) or "##" in t or "#@#" in t or any(c in t for c in "*^$"):
            return t if " " not in t or "##" in t else ""
        return ""

    def add_rule(self, text):
        r = self.parse_rule(text)
        if r and r not in self.custom_lines:
            self.custom_lines.append(r)
            self._sync_custom()
            self.save_custom()
            self.filters.rebuild()
        return r

    def remove_rule(self, rule):
        for cand in (rule, "||" + rule + "^"):
            if cand in self.custom_lines:
                self.custom_lines.remove(cand)
        self._sync_custom()
        self.save_custom()
        self.filters.rebuild()

    def set_allowed(self, host, allowed):
        (self.allowlist.add if allowed else self.allowlist.discard)(host.lower())
        self.save_custom()
        self._cache.clear()

    def is_allowed(self, host):
        h = (host or "").lower()
        return _host_in(h, self.allowlist) or _host_in(h, self.site_allow)

    def stats_for(self, host):
        return self.per_site.get(host, 0)

    def rule_count(self):
        return self.filters.rules or (len(self.ads) + len(self.trackers) + len(self.custom_lines))

    # ---- interception (IO thread) --------------------------------------------------------------------
    def interceptRequest(self, info):
        try:
            url = info.requestUrl()
            scheme = url.scheme()
            if scheme not in ("http", "https", "ws", "wss"):
                return
            if self.send_dnt:
                info.setHttpHeader(b"DNT", b"1")
                info.setHttpHeader(b"Sec-GPC", b"1")
            if not self.enabled:
                return
            rtype = info.resourceType()
            main = rtype == RT.ResourceTypeMainFrame     # the page the user asked for is never blocked, but tracking parameters are stripped
            first_url = info.firstPartyUrl()
            first = first_url.host().lower()
            if first and (self.allowlist or self.site_allow) and (_host_in(first, self.allowlist) or _host_in(first, self.site_allow)):
                return
            engine = self.filters.engine
            if engine is None:
                self._legacy(info, url, first)
                return
            full = url.toString(FULL)
            key = (full, first, rtype)
            res = self._cache.get(key)
            if res is None:
                res = engine.check(full, first_url.toString(FULL) if first else "", "websocket" if scheme in ("ws", "wss") else _TYPES.get(rtype, "other"))
                if len(self._cache) >= CACHE_MAX:
                    self._cache.clear()
                self._cache[key] = res
            blocked, redirect, rewritten = res
            if main:
                blocked = False
            if blocked:
                stub = self._stub_url(redirect) if redirect else None
                if stub is not None:
                    info.redirect(stub)
                    self.redirected += 1
                else:
                    info.block(True)
                self._count(first)
            elif rewritten and rewritten != full:
                info.redirect(QUrl(rewritten))           # tracking parameters removed ($removeparam)
        except BaseException:                            # never let anything escape into Chromium's IO thread (a Rust panic is a BaseException)
            log.debug("interceptor error", exc_info=True)

    def _stub_url(self, data_url):
        """Chromium refuses redirects to data: URLs, so a redirect resource is served by our own scheme handler instead."""
        if not data_url.startswith("data:") or ";base64," not in data_url:
            return None
        key = hashlib.sha1(data_url.encode()).hexdigest()[:20]
        if key not in self._stubs:
            head, payload = data_url[5:].split(";base64,", 1)
            try:
                self._stubs[key] = (head or "application/octet-stream", base64.b64decode(payload))
            except ValueError:
                return None
        return QUrl("null://stub/" + key)

    def stub(self, key):
        return self._stubs.get(key)

    def _count(self, first):
        self.total += 1
        self.per_site[first] += 1
        self.blocked.emit(first)

    def _legacy(self, info, url, first):
        """Domain-list matcher used only until the engine is ready (or if no engine could be built)."""
        host = url.host().lower()
        third_party = (not first) or _registrable(host) != _registrable(first)
        hit = _host_in(host, self.custom) or (third_party and (_host_in(host, self.ads) or (self.block_trackers and _host_in(host, self.trackers))))
        if hit:
            info.block(True)
            self._count(first)
