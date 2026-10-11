"""Request interceptor: ad / tracker blocking, DNT + Global Privacy Control headers.

Runs on Chromium's IO thread - keep it allocation-light and never touch widgets here.
"""
import json
import logging
import os
from collections import Counter

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWebEngineCore import QWebEngineUrlRequestInterceptor, QWebEngineUrlRequestInfo

from . import paths

log = logging.getLogger("null.adblock")
LIST_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "blocklist.txt")
RT = QWebEngineUrlRequestInfo.ResourceType


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
        self.ads, self.trackers, self.custom = set(), set(), set()
        self.allowlist = set()
        self.site_allow = set()
        self.safe_mode = False
        self.total = 0
        self.per_site = Counter()
        self.enabled = True
        self.block_trackers = True
        self.send_dnt = True
        self.load_lists()
        self.refresh()

    def refresh(self):
        self.enabled = bool(self.settings.get("adblock")) and not self.safe_mode
        if self.perms is not None and self.perms.default("intrusive_ads") == "allow":
            self.enabled = False
        self.site_allow = set()
        if self.perms is not None:
            for (origin, feat), val in list(self.perms.cache.items()):
                if feat == "intrusive_ads" and val == "allow":
                    self.site_allow.add(origin.split("://", 1)[-1].split(":")[0].lower())
        self.block_trackers = bool(self.settings.get("block_trackers"))
        self.send_dnt = bool(self.settings.get("send_dnt"))

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
            log.warning("blocklist.txt not found; ad blocking limited to custom rules")
        self.ads, self.trackers = ads, trackers
        try:
            with open(self._custom_path(), encoding="utf-8") as f:
                d = json.load(f)
            self.custom = {x.lower() for x in d.get("rules", [])}
            self.allowlist = {x.lower() for x in d.get("allow", [])}
        except (OSError, ValueError):
            self.custom, self.allowlist = set(), set()

    def save_custom(self):
        try:
            with open(self._custom_path(), "w", encoding="utf-8") as f:
                json.dump({"rules": sorted(self.custom), "allow": sorted(self.allowlist)}, f, indent=2)
        except OSError:
            log.exception("could not save custom adblock rules")

    @staticmethod
    def parse_rule(text):
        t = text.strip().lower()
        if t.startswith("||"):
            t = t[2:]
        t = t.split("^")[0].split("/")[0].split("$")[0].strip(".")
        return t if "." in t and " " not in t else ""

    def add_rule(self, text):
        r = self.parse_rule(text)
        if r:
            self.custom.add(r)
            self.save_custom()
        return r

    def remove_rule(self, rule):
        self.custom.discard(rule)
        self.save_custom()

    def set_allowed(self, host, allowed):
        (self.allowlist.add if allowed else self.allowlist.discard)(host.lower())
        self.save_custom()

    def is_allowed(self, host):
        h = (host or "").lower()
        return _host_in(h, self.allowlist) or _host_in(h, self.site_allow)

    def stats_for(self, host):
        return self.per_site.get(host, 0)

    def rule_count(self):
        return len(self.ads) + len(self.trackers) + len(self.custom)

    # interception (IO thread) ---------------------------------------------------------
    def interceptRequest(self, info):
        try:
            url = info.requestUrl()
            if url.scheme() not in ("http", "https", "ws", "wss"):
                return
            if self.send_dnt:
                info.setHttpHeader(b"DNT", b"1")
                info.setHttpHeader(b"Sec-GPC", b"1")
            if not self.enabled:
                return
            if info.resourceType() == RT.ResourceTypeMainFrame:
                return                                   # never block the page the user typed
            host = url.host().lower()
            first_url = info.firstPartyUrl()
            first = first_url.host().lower()
            if first and (self.allowlist or self.site_allow) and (_host_in(first, self.allowlist) or _host_in(first, self.site_allow)):
                return
            third_party = (not first) or _registrable(host) != _registrable(first)
            hit = False
            if _host_in(host, self.custom):
                hit = True
            elif third_party and (_host_in(host, self.ads) or (self.block_trackers and _host_in(host, self.trackers))):
                hit = True
            if hit:
                info.block(True)
                self.total += 1
                self.per_site[first] += 1
                self.blocked.emit(first)
        except Exception:                                # never let the interceptor throw
            log.debug("interceptor error", exc_info=True)
