"""The null:// URL scheme: built-in pages (history, settings, ...) served from inside the browser.

 * null://<page>[/path]      -> HTML shell for the page (pages/page.html + static/<page>.js)
 * null://<page>/_/<file>    -> static assets (css/js/svg)
 * null://<page>/_/favicon   -> cached favicons from the local database (no network)
 * null://<page>/api/<name>  -> JSON API used by the pages; only callable from null:// pages
"""
import json
import logging
import mimetypes
import os
import re
import secrets
import time
import traceback
from urllib.parse import parse_qs

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QUrl
from PyQt6.QtWebEngineCore import QWebEngineUrlScheme, QWebEngineUrlSchemeHandler, QWebEngineUrlRequestJob

from ..constants import SCHEME
from . import api as api_mod

log = logging.getLogger("null.scheme")
HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
PAGES = os.path.join(HERE, "pages")

PAGE_TITLES = {"newtab": "New Tab", "history": "History", "bookmarks": "Bookmarks", "downloads": "Downloads",
               "settings": "Settings", "about": "About Null Browser", "version": "Version", "logs": "Logs & errors",
               "error": "Error"}
CSP = ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")

# Per-process secret embedded in the browser's own pages and required on every API call. Web content cannot read
# null:// pages (cross-origin), so it can never learn it - this does not depend on how Chromium serialises the
# origin of a custom scheme (which is opaque, i.e. "null").
API_TOKEN = secrets.token_urlsafe(24)
MAX_BODY = 12_000                      # bytes: largest single API request body (bigger payloads are sent in chunks)
FOREIGN_SCHEMES = {"http", "https", "file", "ftp", "ws", "wss", "data", "blob", "filesystem", "view-source"}

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("image/svg+xml", ".svg")


def register_scheme():
    """Must run before QApplication is created."""
    scheme = QWebEngineUrlScheme(SCHEME.encode())
    scheme.setSyntax(QWebEngineUrlScheme.Syntax.Host)
    scheme.setDefaultPort(QWebEngineUrlScheme.SpecialPort.PortUnspecified.value)
    scheme.setFlags(QWebEngineUrlScheme.Flag.SecureScheme
                    | QWebEngineUrlScheme.Flag.FetchApiAllowed | QWebEngineUrlScheme.Flag.ViewSourceAllowed)
    QWebEngineUrlScheme.registerScheme(scheme)


class NullSchemeHandler(QWebEngineUrlSchemeHandler):
    def __init__(self, app, private=False, parent=None):
        super().__init__(parent)
        self.app = app
        self.private = private
        self._tpl = None

    def template(self):
        if self._tpl is None:
            with open(os.path.join(PAGES, "page.html"), encoding="utf-8") as f:
                self._tpl = f.read()
        return self._tpl

    def requestStarted(self, job):
        try:
            self._serve(job)
        except Exception:                                       # a bad page must never crash the browser
            log.exception("scheme handler failed for %s", job.requestUrl().toString())
            try:
                self._reply(job, b"<h1>Internal error</h1><p>See null://logs</p>", "text/html", 500)
            except Exception:
                job.fail(QWebEngineUrlRequestJob.Error.RequestFailed)

    def _reply(self, job, data, mime, status=200, extra=None):
        buf = QBuffer(job)
        buf.setData(QByteArray(data))
        buf.open(QIODevice.OpenModeFlag.ReadOnly)
        # PyQt6 wants {name: [values]}: a bare QByteArray value is iterated byte by byte ("d, e, f, a, ...").
        values = {"Content-Security-Policy": CSP, "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
        values.update(extra or {})
        try:
            job.setAdditionalResponseHeaders({QByteArray(k.encode()): [QByteArray(v.encode())] for k, v in values.items()})
        except Exception:
            log.exception("could not set security headers on a null:// response")
        job.reply(mime.encode(), buf)

    def _serve(self, job):
        url = job.requestUrl()
        host = (url.host() or "").lower()
        path = url.path() or "/"
        query = {k: v[-1] for k, v in parse_qs(url.query()).items()}

        if path.startswith("/api/"):
            return self._api(job, path[5:], query)
        if path.startswith("/_/"):
            name = path[3:]
            if name == "favicon":
                return self._favicon(job, query.get("u", ""), strict=query.get("strict") == "1")
            if name == "bg":
                return self._newtab_bg(job)
            safe = os.path.normpath(name)
            if safe.startswith("..") or os.path.isabs(safe):
                return job.fail(QWebEngineUrlRequestJob.Error.UrlInvalid)
            full = os.path.join(STATIC, safe)
            if not os.path.isfile(full):
                return job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
            with open(full, "rb") as f:
                return self._reply(job, f.read(), mimetypes.guess_type(full)[0] or "application/octet-stream",
                                   extra={"Cache-Control": "max-age=60"})
        if host not in PAGE_TITLES:
            return self._reply(job, self._not_found(url.toString()).encode(), "text/html", 404)
        return self._reply(job, self._render(host, PAGE_TITLES[host]).encode(), "text/html")

    def _not_found(self, url):
        from urllib.parse import quote
        target = f"{SCHEME}://error?kind=net&code=ERR_FILE_NOT_FOUND&u={quote(url, safe='')}"
        return f'<!doctype html><meta charset="utf-8"><title>Not found</title><body><script src="/_/icons.js"></script><script src="/_/ui.js"></script><script>location.replace({json.dumps(target)})</script>'

    def _render(self, page, title):
        s = self.app.settings
        theme = "dark" if self.private else (s.get("theme") or "system")
        accent = s.get("accent") or "#6c5ce7"
        return (self.template().replace("{{theme}}", theme).replace("{{accent}}", accent)
                .replace("{{accent_contrast}}", _contrast(accent)).replace("{{page}}", page).replace("{{title}}", title)
                .replace("{{token}}", API_TOKEN))

    def _newtab_bg(self, job):
        found = api_mod.newtab_bg_file()
        if not found:
            return job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
        path, mime = found
        with open(path, "rb") as f:
            return self._reply(job, f.read(), mime, extra={"Cache-Control": "no-store"})

    def _favicon(self, job, u, strict=False):
        host = QUrl(u).host() or ""
        png = self.app.db.favicon(host) if host else None
        if png:
            return self._reply(job, bytes(png), "image/png", extra={"Cache-Control": "max-age=300"})
        if strict:                                           # caller draws its own fallback (e.g. a letter avatar)
            return job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#9a9db3" stroke-width="1.6">'
               '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18"/></svg>')
        self._reply(job, svg.encode(), "image/svg+xml")

    def _api(self, job, name, query):
        init = job.initiator()
        if init.scheme().lower() in FOREIGN_SCHEMES:
            log.warning("Blocked API call %s from foreign origin %s", name, init.toString())
            return job.fail(QWebEngineUrlRequestJob.Error.RequestDenied)
        token = ""
        for k, v in job.requestHeaders().items():
            if bytes(k).lower() == b"x-null-token":
                token = bytes(v).decode("latin-1")
        if not secrets.compare_digest(token, API_TOKEN):
            log.warning("Blocked API call %s without a valid token (initiator %r)", name, init.toString())
            return job.fail(QWebEngineUrlRequestJob.Error.RequestDenied)
        params = dict(query)
        if job.requestMethod() == b"POST":
            body = job.requestBody()
            if body is not None:
                # NOTE: a blocking readAll() only works while the whole body fits in the first network chunk (~16 KB);
                # anything larger deadlocks the UI thread. Pages therefore split big payloads (see api() in ui.js and
                # the blob/put route), and we refuse anything that announces a larger body instead of freezing.
                for k, v in job.requestHeaders().items():
                    if bytes(k).lower() == b"content-length" and int(bytes(v) or 0) > MAX_BODY:
                        return self._reply(job, b'{"error":"Request too large"}', "application/json", 413)
                try:
                    body.open(QIODevice.OpenModeFlag.ReadOnly)
                    raw = bytes(body.readAll())
                    if raw:
                        params.update(json.loads(raw.decode("utf-8")))
                except (ValueError, UnicodeDecodeError):
                    return self._reply(job, b'{"error":"Invalid JSON"}', "application/json", 400)
        return self._run_api(job, name, params)

    def _run_api(self, job, name, params):
        try:
            result = api_mod.dispatch(self.app, name, params, private=self.private)
            return self._reply(job, json.dumps(result, default=str).encode(), "application/json")
        except api_mod.ApiError as exc:
            return self._reply(job, json.dumps({"error": str(exc)}).encode(), "application/json", 400)
        except Exception as exc:
            tb = traceback.format_exc()
            log.error("API %s failed: %s\n%s", name, exc, tb)
            from ..core import crash
            crash.ERRORS.append({"t": time.time(), "title": f"API {name}: {exc}", "trace": tb})
            return self._reply(job, json.dumps({"error": f"{type(exc).__name__}: {exc}"}).encode(), "application/json", 500)


def _contrast(hex_color):
    m = re.match(r"^#?([0-9a-fA-F]{2})([0-9a-fA-F]{2})([0-9a-fA-F]{2})$", hex_color or "")
    if not m:
        return "#ffffff"
    r, g, b = (int(x, 16) for x in m.groups())
    return "#111111" if (0.299 * r + 0.587 * g + 0.114 * b) > 170 else "#ffffff"
