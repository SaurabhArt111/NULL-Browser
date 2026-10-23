"""JSON API behind the null:// pages. Every handler is (app, params, private) -> JSON-able."""
import base64
import glob
import html as H
import json
import logging
import os
import re
import subprocess
import sys
import urllib.request
from urllib.parse import urlsplit

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QFileDialog

from ..core import crash, permissions

log = logging.getLogger("null.api")
ROUTES = {}


class ApiError(Exception):
    pass


def route(name):
    def deco(fn):
        ROUTES[name] = fn
        return fn
    return deco


BLOBS = {}                                  # id -> {"parts": {i: str}, "n": int, "t": time}; large request bodies arrive in pieces
BLOB_LIMIT = 40_000_000


def dispatch(app, name, params, private=False):
    fn = ROUTES.get(name)
    if not fn:
        raise ApiError(f"Unknown API: {name}")
    if params.get("_blob"):                                    # payload that was uploaded in pieces via blob/put
        entry = BLOBS.pop(str(params["_blob"]), None)
        if not entry or len(entry["parts"]) != entry["n"]:
            raise ApiError("Upload incomplete")
        try:
            params = json.loads("".join(entry["parts"][i] for i in range(entry["n"])))
        except (ValueError, KeyError):
            raise ApiError("Upload corrupted")
    return fn(app, params, private)


@route("blob/put")
def blob_put(app, p, private):
    import time
    _need(p, "id", "i", "n", "data")
    now = time.time()
    for k in [k for k, v in BLOBS.items() if now - v["t"] > 300]:       # forget abandoned uploads
        BLOBS.pop(k, None)
    n, i = int(p["n"]), int(p["i"])
    if not (0 <= i < n <= 4000) or not isinstance(p["data"], str) or len(p["data"]) > 12_000:
        raise ApiError("Bad upload piece")
    e = BLOBS.setdefault(str(p["id"]), {"parts": {}, "n": n, "t": now})
    e["parts"][i] = p["data"]
    if sum(len(x) for v in BLOBS.values() for x in v["parts"].values()) > BLOB_LIMIT:
        BLOBS.clear()
        raise ApiError("Upload too large")
    return {"ok": True}


def _need(p, *keys):
    for k in keys:
        if k not in p or p[k] is None:
            raise ApiError(f"Missing parameter: {k}")


def _clean_url(u):
    u = (u or "").strip()
    if not u:
        raise ApiError("URL is required")
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", u):
        u = "https://" + u
    if urlsplit(u).scheme.lower() not in ("http", "https", "file", "ftp", "null"):
        raise ApiError("Only http, https, file and null URLs can be bookmarked")
    return u


# ------------------------------------------------------------------ settings
@route("settings/get")
def settings_get(app, p, private):
    from ..core.settings import RESTART_KEYS
    from ..core import paths
    cookies = app.perms.default("cookies")
    label = next(o["label"] for o in permissions.BY_ID["cookies"]["options"] if o["value"] == cookies)
    return {
        "settings": app.settings.all(), "restart_keys": sorted(RESTART_KEYS), "catalog": app.perms.catalog_with_state(),
        "video": app.video.info(), "engines": app.search.engines(), "engine": app.engine.info(), "perm_defaults": {"cookies_label": label},
        "meta": {"data_dir": paths.data_dir(), "default_download_dir": paths.downloads_dir(), "versions": app.versions(),
                 "bookmark_count": len(app.db.bookmarks())},
    }


@route("settings/set")
def settings_set(app, p, private):
    _need(p, "key", "value")
    if not app.settings.set(p["key"], p["value"]):
        raise ApiError("Unknown setting")
    return {"ok": True}


@route("settings/reset")
def settings_reset(app, p, private):
    app.settings.reset()
    return {"ok": True}


# ------------------------------------------------------------------ permissions
@route("perm/catalog")
def perm_catalog(app, p, private):
    return {"catalog": app.perms.catalog_with_state()}


@route("perm/set_default")
def perm_set_default(app, p, private):
    _need(p, "feature", "value")
    if not app.perms.set_default(p["feature"], p["value"]):
        raise ApiError("Invalid value for this setting")
    app.apply_global_policies()
    return {"ok": True}


@route("perm/sites")
def perm_sites(app, p, private):
    return {"items": app.db.site_perms_list(p.get("feature"))}


@route("perm/set_site")
def perm_set_site(app, p, private):
    _need(p, "origin", "feature", "value")
    origin = p["origin"].strip()
    if "://" not in origin:
        origin = "https://" + origin
    origin = permissions.origin_of(origin)
    if not origin:
        raise ApiError("That doesn't look like a website address")
    if not app.perms.set_site(origin, p["feature"], p["value"]):
        raise ApiError("Invalid permission value")
    app.apply_site_policies()
    return {"ok": True, "origin": origin}


@route("perm/reset_site")
def perm_reset_site(app, p, private):
    _need(p, "origin")
    app.perms.reset_site(p["origin"])
    app.apply_site_policies()
    return {"ok": True}


@route("perm/reset_all")
def perm_reset_all(app, p, private):
    app.perms.reset_all_sites()
    app.apply_site_policies()
    return {"ok": True}


# ------------------------------------------------------------------ history / privacy
@route("history/list")
def history_list(app, p, private):
    return {"items": app.db.history(p.get("q", ""), min(int(p.get("limit", 150)), 500), p.get("before"))}


@route("history/delete")
def history_delete(app, p, private):
    app.db.delete_visits([int(i) for i in p.get("ids", [])])
    return {"ok": True}


@route("privacy/clear")
def privacy_clear(app, p, private):
    app.clear_data(set(p.get("types", [])), p.get("range", "all"))
    return {"ok": True}


# ------------------------------------------------------------------ bookmarks
@route("bookmarks/list")
def bookmarks_list(app, p, private):
    return {"items": app.db.bookmarks(), "folders": app.db.bookmark_folders()}


@route("bookmarks/add")
def bookmarks_add(app, p, private):
    bid = app.db.add_bookmark(p.get("title", ""), _clean_url(p.get("url")), p.get("folder") or "Bookmarks bar")
    app.bookmarks_changed()
    return {"id": bid}


@route("bookmarks/update")
def bookmarks_update(app, p, private):
    _need(p, "id")
    ok = app.db.update_bookmark(int(p["id"]), p.get("title"), _clean_url(p["url"]) if p.get("url") else None, p.get("folder"))
    app.bookmarks_changed()
    if not ok:
        raise ApiError("Bookmark not found")
    return {"ok": True}


@route("bookmarks/delete")
def bookmarks_delete(app, p, private):
    _need(p, "id")
    app.db.delete_bookmark(int(p["id"]))
    app.bookmarks_changed()
    return {"ok": True}


@route("bookmarks/export")
def bookmarks_export(app, p, private):
    out = ['<!DOCTYPE NETSCAPE-Bookmark-file-1>', '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">',
           '<TITLE>Bookmarks</TITLE>', '<H1>Bookmarks</H1>', '<DL><p>']
    by = {}
    for b in app.db.bookmarks():
        by.setdefault(b["folder"], []).append(b)
    for folder, items in by.items():
        out.append(f'  <DT><H3>{H.escape(folder)}</H3>\n  <DL><p>')
        for b in items:
            out.append(f'    <DT><A HREF="{H.escape(b["url"], quote=True)}" ADD_DATE="{int(b["created"] or 0)}">{H.escape(b["title"] or b["url"])}</A>')
        out.append('  </DL><p>')
    out.append('</DL><p>')
    return {"html": "\n".join(out)}


@route("bookmarks/import")
def bookmarks_import(app, p, private):
    text = p.get("html", "")
    if len(text) > 20_000_000:
        raise ApiError("File too large")
    added, stack = 0, ["Other bookmarks"]
    existing = {b["url"] for b in app.db.bookmarks()}
    for m in re.finditer(r'<H3[^>]*>(.*?)</H3>|<A[^>]*HREF="([^"]+)"[^>]*>(.*?)</A>|</DL>', text, re.I | re.S):
        if m.group(1) is not None:
            stack.append(H.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip() or "Imported")
        elif m.group(2):
            url = H.unescape(m.group(2))
            if urlsplit(url).scheme.lower() in ("http", "https") and url not in existing:
                app.db.add_bookmark(H.unescape(re.sub(r"<[^>]+>", "", m.group(3))).strip(), url, stack[-1])
                existing.add(url)
                added += 1
        elif len(stack) > 1:
            stack.pop()
    app.bookmarks_changed()
    return {"added": added}


# ------------------------------------------------------------------ downloads
@route("downloads/list")
def downloads_list(app, p, private):
    return {"items": app.downloads.list()}


def _download_action(method):
    def handler(app, p, private):
        _need(p, "id")
        getattr(app.downloads, method)(int(p["id"]))
        return {"ok": True}
    return handler


for _name, _method in (("cancel", "cancel"), ("pause", "pause"), ("resume", "resume"), ("open", "open_file"), ("show", "show"), ("remove", "remove")):
    ROUTES[f"downloads/{_name}"] = _download_action(_method)


@route("downloads/clear")
def downloads_clear(app, p, private):
    app.downloads.clear_finished()
    return {"ok": True}


# ------------------------------------------------------------------ new tab / search
@route("search/resolve")
def search_resolve(app, p, private):
    url, is_search = app.resolve_text(p.get("q", ""))
    return {"url": url or "null://newtab", "search": is_search}


@route("newtab/data")
def newtab_data(app, p, private):
    top = []
    if not private:
        seen = set()
        for r in app.db.top_sites(12):
            host = urlsplit(r["url"]).netloc
            if host and host not in seen:
                seen.add(host)
                top.append(r)
    bars = [] if private else app.db.bookmarks("Bookmarks bar")[:10]
    return {"engines": app.search.engines(), "engine": app.search.current()["id"], "top": top[:10],
            "bookmarks": bars, "null_search": app.engine.info(), "private": private,
            "newtab": app.settings.get("newtab") or {}, "has_bg": bool(newtab_bg_file())}


# New Tab page background image (uploaded by the user, stored next to settings.json, never leaves the computer)
BG_TYPES = {".jpg": ("image/jpeg", b"\xff\xd8\xff"), ".png": ("image/png", b"\x89PNG\r\n\x1a\n"), ".webp": ("image/webp", b"RIFF"),
            ".gif": ("image/gif", b"GIF8")}


def _bg_dir():
    from ..core import paths
    return paths.sub("newtab")


def newtab_bg_file():
    for ext, (mime, _magic) in BG_TYPES.items():
        p = os.path.join(_bg_dir(), "bg" + ext)
        if os.path.isfile(p):
            return p, mime
    return None


def _drop_bg():
    for p in glob.glob(os.path.join(_bg_dir(), "bg.*")):
        try:
            os.remove(p)
        except OSError:
            pass


@route("newtab/set_bg")
def newtab_set_bg(app, p, private):
    m = re.match(r"^data:image/(jpeg|png|webp|gif);base64,([A-Za-z0-9+/=\s]+)$", p.get("data") or "")
    if not m:
        raise ApiError("Unsupported image")
    if len(m.group(2)) > 14_000_000:
        raise ApiError("That image is too large (limit about 10 MB)")
    try:
        raw = base64.b64decode(m.group(2), validate=False)
    except ValueError:
        raise ApiError("Unreadable image")
    ext = ".jpg" if m.group(1) == "jpeg" else "." + m.group(1)
    if not raw.startswith(BG_TYPES[ext][1]):
        raise ApiError("That file is not a valid image")
    _drop_bg()
    with open(os.path.join(_bg_dir(), "bg" + ext), "wb") as f:
        f.write(raw)
    return {"ok": True}


@route("newtab/clear_bg")
def newtab_clear_bg(app, p, private):
    _drop_bg()
    return {"ok": True}


# ------------------------------------------------------------------ adblock
@route("adblock/info")
def adblock_info(app, p, private):
    a = app.adblock
    fm = a.filters
    custom = [r[2:-1] if r in {"||" + d + "^" for d in a.custom} else r for r in a.custom_lines]
    return {"custom": custom, "allow": sorted(a.allowlist), "rules_total": a.rule_count(), "blocked_total": a.total,
            "redirected_total": a.redirected, "backend": a.backend_label, "building": fm.building, "message": fm.message,
            "updating": fm.updating, "update_error": fm.update_error, "last_update": fm.last_update(),
            "lists": fm.lists_info(), "auto_update": bool(app.settings.get("adblock_auto_update")),
            "cosmetic": bool(app.settings.get("adblock_cosmetic")),
            "video_safe": bool(app.settings.get("adblock_video_safe")), "policy": dict(getattr(fm, "policy_report", {}) or {})}


@route("adblock/set_list")
def adblock_set_list(app, p, private):
    return {"ok": app.adblock.filters.set_enabled(str(p.get("id", "")), bool(p.get("on")))}


@route("adblock/update")
def adblock_update(app, p, private):
    app.adblock.filters.update_all()
    return {"ok": True}


@route("adblock/reset_lists")
def adblock_reset_lists(app, p, private):
    app.adblock.filters.reset_updates()
    return {"ok": True}


@route("adblock/add_rule")
def adblock_add(app, p, private):
    return {"rule": app.adblock.add_rule(p.get("rule", ""))}


@route("adblock/remove_rule")
def adblock_remove(app, p, private):
    app.adblock.remove_rule(p.get("rule", ""))
    return {"ok": True}


@route("adblock/allow")
def adblock_allow(app, p, private):
    app.adblock.set_allowed(p.get("host", ""), bool(p.get("allow")))
    app.refresh_shield()
    return {"ok": True}


# ------------------------------------------------------------------ engine
@route("engine/info")
def engine_info(app, p, private):
    return app.engine.info()


@route("engine/start")
def engine_start(app, p, private):
    app.engine.start()
    return {"ok": True}


@route("engine/stop")
def engine_stop(app, p, private):
    app.engine.stop()
    return {"ok": True}


@route("engine/index_bookmarks")
def engine_index_bookmarks(app, p, private):
    urls = [b["url"] for b in app.db.bookmarks() if b["url"].startswith(("http://", "https://"))]
    if not urls:
        return {"message": "You have no bookmarks to index yet."}
    if app.engine.state not in ("running", "external"):
        return {"message": "Start Null Search first (Server status -> Start)."}
    body = json.dumps({"urls": urls[:50], "max_pages": min(500, 5 * len(urls)), "depth": 1, "same_site": True}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{app.engine.port}/api/crawl", data=body,
                                 headers={"Content-Type": "application/json", "X-Null-Search": "1"})
    try:
        with urllib.request.urlopen(req, timeout=4):
            pass
        return {"message": f"Indexing {len(urls[:50])} bookmark(s) in the background…"}
    except Exception as exc:
        return {"message": f"Could not start indexing: {exc}"}


# ------------------------------------------------------------------ app / about / logs
@route("about/info")
def about_info(app, p, private):
    pages = [("null://newtab", "plus", "Search box and shortcuts"), ("null://history", "history", "Browse and delete visited pages"),
             ("null://bookmarks", "bookmark", "Manage, import and export bookmarks"), ("null://downloads", "download", "Live downloads and history"),
             ("null://settings", "settings", "Privacy, site permissions, appearance, search and more"), ("null://settings/content", "sliders", "All permission defaults and exceptions"),
             ("null://version", "cpu", "Engine and build information"), ("null://logs", "bug", "Self-healing error handler output"), ("null://about", "info", "This page")]
    sc = [("Ctrl+T", "New tab"), ("Ctrl+N", "New window"), ("Ctrl+Shift+N", "New InPrivate window"), ("Ctrl+W", "Close tab"), ("Ctrl+Shift+T", "Reopen closed tab"),
          ("Ctrl+L / F6", "Focus address bar"), ("Ctrl+K / Ctrl+E", "Search from address bar"), ("Ctrl+D", "Bookmark this page"), ("Ctrl+Shift+B", "Show / hide bookmarks bar"),
          ("Ctrl+H", "History"), ("Ctrl+J", "Downloads"), ("Ctrl+Shift+O", "Bookmark manager"), ("Ctrl+,", "Settings"), ("Ctrl+Shift+Del", "Clear browsing data"),
          ("Ctrl+F / F3", "Find in page"), ("Ctrl+P", "Print"), ("Ctrl+S", "Save page"), ("Ctrl+U", "View page source"), ("F12 / Ctrl+Shift+I", "Developer tools"), ("Ctrl+Shift+J", "JavaScript console"),
          ("Ctrl+Shift+C", "Inspect element"), ("Ctrl+Shift+M", "Device mode (responsive / mobile)"), ("Ctrl+M", "Mute / unmute tab"),
          ("Ctrl +/- / 0", "Zoom in / out / reset"), ("F11", "Full screen"), ("Ctrl+Tab / Ctrl+Shift+Tab", "Next / previous tab"), ("Ctrl+1…9", "Jump to tab"), ("Alt+←/→", "Back / forward")]
    return {"versions": app.versions(), "pages": [{"url": u, "icon": i, "desc": d} for u, i, d in pages], "shortcuts": sc}


@route("logs/get")
def logs_get(app, p, private):
    return {"errors": list(crash.ERRORS)[-100:], "log": list(crash.RING)[-400:]}


@route("app/restart")
def app_restart(app, p, private):
    safe = bool(p.get("safe"))
    QTimer.singleShot(150, lambda: app.restart(safe=safe))
    return {"ok": True}


@route("app/open_data_dir")
def app_open_data_dir(app, p, private):
    from ..core import paths
    QDesktopServices.openUrl(QUrl.fromLocalFile(paths.data_dir()))
    return {"ok": True}


@route("app/pick_folder")
def app_pick_folder(app, p, private):
    return {"path": QFileDialog.getExistingDirectory(app.active_window(), "Choose download folder")}


@route("app/set_default_browser")
def app_default(app, p, private):
    if sys.platform.startswith("win"):
        QDesktopServices.openUrl(QUrl("ms-settings:defaultapps"))
    elif sys.platform == "darwin":
        QDesktopServices.openUrl(QUrl("x-apple.systempreferences:com.apple.preference.general"))
    else:
        try:
            subprocess.Popen(["xdg-settings", "set", "default-web-browser", "null-browser.desktop"])
        except Exception:
            pass
    return {"ok": True}


@route("error/proceed")
def error_proceed(app, p, private):
    host = urlsplit(p.get("url", "")).hostname
    if host:
        app.cert_allow.add(host)
    return {"ok": True}
