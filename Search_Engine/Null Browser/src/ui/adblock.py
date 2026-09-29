"""
adblock.py - Brave-style ad & tracker blocking for Null Browser.

Implements a QWebEngineUrlRequestInterceptor that blocks network requests
whose host matches a known ad/tracker blocklist, or whose path matches a
handful of common ad-path patterns. Ships with a compact built-in list
(no network access required) and supports user-supplied custom rules and
a per-site allow-list ("Don't block on this site").
"""
import json
import os
import re
from PyQt6.QtCore import QObject, QSettings, QUrl, pyqtSignal
from PyQt6.QtWebEngineCore import QWebEngineUrlRequestInterceptor

# A compact, curated list of well-known ad / tracker / telemetry domains.
# This intentionally avoids shipping a giant EasyList copy so the app stays
# lightweight; users can extend it from Settings > Privacy > Custom rules.
BUILTIN_BLOCKLIST = {
    "doubleclick.net", "googlesyndication.com", "googleadservices.com",
    "google-analytics.com", "googletagmanager.com", "googletagservices.com",
    "adservice.google.com", "adnxs.com", "adsrvr.org", "advertising.com",
    "adform.net", "adroll.com", "criteo.com", "criteo.net", "outbrain.com",
    "taboola.com", "scorecardresearch.com", "quantserve.com", "moatads.com",
    "media.net", "pubmatic.com", "rubiconproject.com", "openx.net",
    "casalemedia.com", "bluekai.com", "mathtag.com", "adsafeprotected.com",
    "amazon-adsystem.com", "facebook.net", "connect.facebook.net",
    "analytics.twitter.com", "ads-twitter.com", "bat.bing.com",
    "hotjar.com", "mixpanel.com", "segment.io", "segment.com", "fullstory.com",
    "yandex.ru/clck", "adjust.com", "appsflyer.com", "branch.io",
    "chartbeat.com", "newrelic.com", "nr-data.net", "sentry.io",
    "vungle.com", "applovin.com", "unityads.unity3d.com", "ironsrc.com",
    "smartadserver.com", "adtechus.com", "adition.com", "yieldmo.com",
    "sharethrough.com", "teads.tv", "spotxchange.com", "tremorhub.com",
    "adcolony.com", "chitika.com", "revcontent.com", "mgid.com",
    "popads.net", "propellerads.com", "exoclick.com", "juicyads.com",
    "trafficjunky.net", "onclickmax.com", "adnium.com", "clicksor.com",
    "zedo.com", "adblade.com", "infolinks.com", "kontera.com",
}

# Path substrings that frequently indicate ad/tracking requests even on
# domains that aren't in the blocklist (e.g. first-party ad proxies).
BLOCKED_PATH_PATTERNS = [
    re.compile(r"/ads?[/_-]", re.I),
    re.compile(r"/advert(is(ing|ement))?/", re.I),
    re.compile(r"/(track|pixel|beacon)(ing)?[./]", re.I),
    re.compile(r"[?&](utm_|gclid=|fbclid=)", re.I),
]

CUSTOM_RULES_FILE = os.path.join(
    os.path.expanduser("~"), ".null_browser", "adblock_custom.json"
)


def _load_custom_rules():
    try:
        if os.path.exists(CUSTOM_RULES_FILE):
            with open(CUSTOM_RULES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data.get("blocked_domains", [])), set(data.get("allowed_sites", []))
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return set(), set()


def _save_custom_rules(blocked_domains, allowed_sites):
    try:
        os.makedirs(os.path.dirname(CUSTOM_RULES_FILE), exist_ok=True)
        with open(CUSTOM_RULES_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "blocked_domains": sorted(blocked_domains),
                    "allowed_sites": sorted(allowed_sites),
                },
                f,
                indent=2,
            )
    except OSError:
        pass


class AdBlocker(QWebEngineUrlRequestInterceptor):
    """Intercepts outgoing requests and blocks known ad/tracker hosts."""

    blocked_count_changed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        custom_blocked, allowed = _load_custom_rules()
        self.blocklist = set(BUILTIN_BLOCKLIST) | custom_blocked
        self.allowed_sites = allowed
        self.enabled = True
        self.total_blocked = 0
        self._session_log = []  # last N blocked urls, for the "shield" popup

    # -- persistence -----------------------------------------------------
    def add_custom_domain(self, domain):
        domain = domain.strip().lower()
        if domain:
            self.blocklist.add(domain)
            self._persist()

    def remove_custom_domain(self, domain):
        self.blocklist.discard(domain.strip().lower())
        self._persist()

    def set_site_allowed(self, host, allowed):
        host = host.strip().lower()
        if allowed:
            self.allowed_sites.add(host)
        else:
            self.allowed_sites.discard(host)
        self._persist()

    def is_site_allowed(self, host):
        return host.strip().lower() in self.allowed_sites

    def _persist(self):
        custom = self.blocklist - BUILTIN_BLOCKLIST
        _save_custom_rules(custom, self.allowed_sites)

    # -- matching ----------------------------------------------------------
    def _host_is_blocked(self, host):
        if not host:
            return False
        host = host.lower()
        # match exact or subdomain
        for blocked in self.blocklist:
            if host == blocked or host.endswith("." + blocked):
                return True
        return False

    def _url_is_blocked(self, url: QUrl, top_level_host: str):
        if not self.enabled:
            return False
        if top_level_host and self.is_site_allowed(top_level_host):
            return False
        host = url.host()
        if self._host_is_blocked(host):
            return True
        path_and_query = url.path() + "?" + url.query()
        for pattern in BLOCKED_PATH_PATTERNS:
            if pattern.search(path_and_query):
                # Don't block first-party navigations, only sub-resources
                return True
        return False

    # -- Qt override ---------------------------------------------------
    def interceptRequest(self, info):
        try:
            url = info.requestUrl()
            first_party = info.firstPartyUrl()
            top_level_host = first_party.host() if first_party else ""

            # Never block the main-frame navigation itself
            from PyQt6.QtWebEngineCore import QWebEngineUrlRequestInfo
            if info.resourceType() == QWebEngineUrlRequestInfo.ResourceType.ResourceTypeMainFrame:
                return

            if self._url_is_blocked(url, top_level_host):
                info.block(True)
                self.total_blocked += 1
                self._session_log.append(url.toString())
                if len(self._session_log) > 200:
                    self._session_log.pop(0)
                self.blocked_count_changed.emit(self.total_blocked)
        except Exception:
            # Never let a bad rule crash the whole browser / page load
            pass

    def recent_blocked(self, limit=25):
        return list(reversed(self._session_log[-limit:]))

    def reset_counter(self):
        self.total_blocked = 0
        self._session_log.clear()
        self.blocked_count_changed.emit(0)
