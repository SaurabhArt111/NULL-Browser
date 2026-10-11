"""Search engines, omnibox input classification and live suggestions."""
import ipaddress
import json
import os
import re
from urllib.parse import quote_plus

from PyQt6.QtCore import QObject, QUrl, pyqtSignal, QTimer
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

from ..constants import SCHEME

ENGINES = {
    "google": {"name": "Google", "keyword": "@google", "url": "https://www.google.com/search?q=%s",
               "suggest": "https://suggestqueries.google.com/complete/search?client=firefox&q=%s",
               "home": "https://www.google.com/"},
    "null": {"name": "Null Search", "keyword": "@null", "url": "http://127.0.0.1:{port}/?q=%s",
             "suggest": "http://127.0.0.1:{port}/api/suggest?q=%s", "home": "http://127.0.0.1:{port}/", "local": True},
    "duckduckgo": {"name": "DuckDuckGo", "keyword": "@ddg", "url": "https://duckduckgo.com/?q=%s",
                   "suggest": "https://duckduckgo.com/ac/?type=list&q=%s", "home": "https://duckduckgo.com/"},
    "bing": {"name": "Bing", "keyword": "@bing", "url": "https://www.bing.com/search?q=%s",
             "suggest": "https://api.bing.com/osjson.aspx?query=%s", "home": "https://www.bing.com/"},
    "brave": {"name": "Brave Search", "keyword": "@brave", "url": "https://search.brave.com/search?q=%s",
              "suggest": "https://search.brave.com/api/suggest?q=%s", "home": "https://search.brave.com/"},
    "ecosia": {"name": "Ecosia", "keyword": "@ecosia", "url": "https://www.ecosia.org/search?q=%s",
               "suggest": "", "home": "https://www.ecosia.org/"},
}

ALIASES = {"chrome": SCHEME, "edge": SCHEME, "brave": SCHEME}
_SCHEME_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.\-]*):")
_HOSTPORT_RE = re.compile(r"^[\w.\-]+:\d{1,5}(/|\?|#|$)")
_DOMAIN_RE = re.compile(r"^(?:[A-Za-z0-9](?:[A-Za-z0-9\-_]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,}(?::\d{1,5})?(?:[/?#].*)?$")


def _is_ip(s):
    try:
        ipaddress.ip_address(s)
        return True
    except ValueError:
        return False


class SearchManager:
    def __init__(self, settings):
        self.settings = settings

    def port(self):
        return int(self.settings.get("null_search_port") or 8000)

    def engines(self):
        out = {}
        for k, e in ENGINES.items():
            d = dict(e)
            for f in ("url", "suggest", "home"):
                d[f] = d[f].replace("{port}", str(self.port()))
            d["id"] = k
            out[k] = d
        for i, c in enumerate(self.settings.get("custom_engines") or []):
            try:
                kid = f"custom{i}"
                out[kid] = {"id": kid, "name": c["name"], "keyword": c.get("keyword") or "@" + c["name"].lower().replace(" ", ""),
                            "url": c["url"], "suggest": "", "home": c["url"].split("%s")[0], "custom": True}
            except (KeyError, TypeError):
                continue
        return out

    def current(self):
        engines = self.engines()
        return engines.get(self.settings.get("search_engine"), engines["google"])

    def search_url(self, query, engine=None):
        e = engine or self.current()
        return e["url"].replace("%s", quote_plus(query))

    def by_keyword(self, text):
        if not text.startswith("@"):
            return None, text
        head, _, rest = text.partition(" ")
        for e in self.engines().values():
            if e["keyword"].lower() == head.lower():
                return e, rest.strip()
        return None, text

    def to_url(self, text):
        """Return (url, is_search). Never raises."""
        text = (text or "").strip()
        if not text:
            return "", False
        if text.startswith("?"):
            return self.search_url(text[1:].strip()), True
        engine, rest = self.by_keyword(text)
        if engine:
            return (self.search_url(rest, engine) if rest else engine["home"]), True
        if text.startswith("@"):
            kw = text[1:].split(" ", 1)
            if kw[0] in ("history", "bookmarks", "downloads", "settings"):
                q = kw[1] if len(kw) > 1 else ""
                return f"{SCHEME}://{kw[0]}" + (f"?q={quote_plus(q)}" if q else ""), False
        if _HOSTPORT_RE.match(text):
            host = text.split(":")[0].lower()
            return ("http://" if host == "localhost" or _is_ip(host) else "https://") + text, False
        m = _SCHEME_RE.match(text)
        if m:
            scheme = m.group(1).lower()
            if scheme in ALIASES and text[len(scheme):].startswith("://"):
                return f"{SCHEME}://{text[len(scheme) + 3:]}", False
            if scheme == "about":
                rest = text[6:].strip("/")
                return ("about:blank" if rest in ("", "blank") else f"{SCHEME}://{rest}"), False
            if scheme in ("http", "https", "file", SCHEME, "view-source", "ftp", "data", "blob"):
                return text, False
            if scheme == "javascript":
                return self.search_url(text), True       # never execute script: URLs from the address bar
            if "://" in text:
                return text, False
        if re.match(r"^([A-Za-z]:[\\/]|\\\\|/|~)", text):
            p = os.path.expanduser(text)
            if os.path.exists(p):
                return QUrl.fromLocalFile(os.path.abspath(p)).toString(), False
        if " " not in text:
            host = re.split(r"[/?#:]", text, 1)[0].lower()
            if host == "localhost" or _is_ip(host.strip("[]")) or text.startswith("["):
                return "http://" + text, False
            if _DOMAIN_RE.match(text):
                return "https://" + text, False
        return self.search_url(text), True


def display_url(url):
    """User-facing URL: hide https:// and a lone trailing slash."""
    s = url
    if s.startswith("https://"):
        s = s[8:]
    if s.endswith("/") and s.count("/") == 1:
        s = s[:-1]
    return s


class SuggestClient(QObject):
    """Debounced search suggestions from the active engine."""
    ready = pyqtSignal(str, list)

    def __init__(self, search, settings, parent=None):
        super().__init__(parent)
        self.search = search
        self.settings = settings
        self.nam = QNetworkAccessManager(self)
        self.timer = QTimer(self, singleShot=True, interval=120)
        self.timer.timeout.connect(self._go)
        self.pending = ""
        self.reply = None

    def request(self, text):
        self.pending = text
        if not self.settings.get("search_suggestions") or len(text.strip()) < 2:
            self.timer.stop()
            return
        self.timer.start()

    def cancel(self):
        self.timer.stop()
        if self.reply:
            self.reply.abort()
            self.reply = None

    def _go(self):
        tpl = self.search.current().get("suggest")
        if not tpl:
            return
        if self.reply:
            self.reply.abort()
        q = self.pending
        req = QNetworkRequest(QUrl(tpl.replace("%s", quote_plus(q))))
        req.setTransferTimeout(3000)
        req.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, "Mozilla/5.0 NullBrowser")
        self.reply = self.nam.get(req)
        rep = self.reply
        rep.finished.connect(lambda: self._done(rep, q))

    def _done(self, rep, q):
        if rep is self.reply:
            self.reply = None
        try:
            if rep.error() != QNetworkReply.NetworkError.NoError:
                return
            raw = bytes(rep.readAll())
            try:
                data = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                data = json.loads(raw.decode("latin-1", "replace"))
            if isinstance(data, dict):
                items = data.get("suggestions", [])
            elif isinstance(data, list) and len(data) > 1 and isinstance(data[1], list):
                items = data[1]
            else:
                items = []
            items = [s if isinstance(s, str) else (s.get("phrase", "") if isinstance(s, dict) else "") for s in items]
            self.ready.emit(q, [s for s in items if s][:6])
        except Exception:
            pass
        finally:
            rep.deleteLater()
