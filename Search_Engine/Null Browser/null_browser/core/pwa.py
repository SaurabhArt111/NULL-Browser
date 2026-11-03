"""Installed web apps (PWAs): the records, manifest parsing and scope rules. No Qt in here, so it is unit-tested directly.

Every installed app gets its **own web profile** (see app_pwa.py): cookies, local storage, IndexedDB, service workers and the
HTTP cache of an app live in their own folder. "Clear browsing data" in the browser works on the browser's profile only, so it can
never touch an app - that is the whole mechanism, there is no exception list that could be forgotten. An app's data is removed
only by uninstalling it or by "Clear this app's data" on the Apps settings page.
"""
import hashlib
import json
import os
import re
import time
from urllib.parse import urljoin, urlsplit

DISPLAYS = ("fullscreen", "standalone", "minimal-ui", "browser")


def app_id_for(start_url):
    """Stable id from the app's origin + path (re-installing the same app gives the same id)."""
    p = urlsplit(start_url)
    slug = re.sub(r"[^a-z0-9]+", "-", (p.hostname or "app").lower()).strip("-")[:24] or "app"
    return f"{slug}-{hashlib.sha1((p.scheme + '://' + p.netloc + p.path.rstrip('/')).encode()).hexdigest()[:6]}"


def origin_of(url):
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}".lower() if p.scheme and p.netloc else ""


def in_scope(url, scope):
    """Is `url` inside the app? Same origin and (when the scope has a path) below that path."""
    u, s = urlsplit(url), urlsplit(scope)
    if u.scheme not in ("http", "https") or origin_of(url) != origin_of(scope):
        return False
    base = s.path or "/"
    if not base.endswith("/"):
        base = base.rsplit("/", 1)[0] + "/"
    return (u.path or "/").startswith(base) or (u.path or "/") + "/" == base


def _color(v):
    return v if isinstance(v, str) and re.fullmatch(r"#[0-9a-fA-F]{3,8}|[a-zA-Z]{3,20}", v.strip()) else ""


def parse_manifest(text, manifest_url, page_url):
    """Normalise a web app manifest. Never raises: a missing / broken manifest gives sensible defaults taken from the page."""
    try:
        m = json.loads(text) if text else {}
        if not isinstance(m, dict):
            m = {}
    except ValueError:
        m = {}
    base = manifest_url or page_url
    page_origin = origin_of(page_url)

    def resolve(u, fallback):
        try:
            full = urljoin(base, u) if isinstance(u, str) and u.strip() else fallback
        except ValueError:
            return fallback
        return full if urlsplit(full).scheme in ("http", "https") else fallback

    start = resolve(m.get("start_url"), page_url)
    if origin_of(start) != page_origin:                    # a manifest cannot move the app to another site
        start = page_url
    scope = resolve(m.get("scope"), start.rsplit("/", 1)[0] + "/" if urlsplit(start).path not in ("", "/") else start)
    if origin_of(scope) != page_origin or not in_scope(start, scope):
        scope = origin_of(start) + "/"
    icons = []
    for ic in m.get("icons") or []:
        if isinstance(ic, dict) and isinstance(ic.get("src"), str):
            src = resolve(ic["src"], "")
            if src:
                sizes = [int(a) for a in re.findall(r"(\d+)x\d+", str(ic.get("sizes") or ""))]
                icons.append({"src": src, "size": max(sizes) if sizes else 0, "purpose": str(ic.get("purpose") or "any")})
    display = m.get("display") if m.get("display") in DISPLAYS else "standalone"
    name = str(m.get("name") or m.get("short_name") or "").strip()[:60]
    return {"name": name, "short_name": str(m.get("short_name") or "").strip()[:30], "start_url": start, "scope": scope, "display": display,
            "theme_color": _color(m.get("theme_color")), "background_color": _color(m.get("background_color")), "icons": icons,
            "manifest_url": manifest_url or ""}


def best_icon(icons, want=192):
    """The icon closest to `want` px (prefers 'any' over 'maskable'); None if there are none."""
    pool = [i for i in icons if "monochrome" not in i["purpose"]] or icons
    if not pool:
        return None
    anyp = [i for i in pool if "maskable" not in i["purpose"]] or pool
    return min(anyp, key=lambda i: (abs((i["size"] or want) - want) + (0 if i["size"] else 40)))


def fingerprint(manifest):
    """Hash of the parts of a manifest that matter to the install; a change means the site updated its app."""
    keep = {k: manifest.get(k) for k in ("name", "short_name", "start_url", "scope", "display", "theme_color", "background_color")}
    keep["icons"] = sorted((i["src"], i["size"]) for i in manifest.get("icons", []))
    return hashlib.sha256(json.dumps(keep, sort_keys=True).encode()).hexdigest()[:16]


class PwaStore:
    """apps.json + icons/ below the pwa folder."""

    def __init__(self, folder):
        self.dir = folder
        self.file = os.path.join(folder, "apps.json")
        os.makedirs(os.path.join(folder, "icons"), exist_ok=True)
        self.apps = {}
        try:
            with open(self.file, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                self.apps = {k: v for k, v in d.items() if isinstance(v, dict) and v.get("start_url")}
        except (OSError, ValueError):
            pass

    def save(self):
        tmp = self.file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.apps, f, indent=2)
        os.replace(tmp, self.file)

    def defer_delete(self, folder):
        """Folders of uninstalled apps that could not be deleted yet (in use); purge_deferred() removes them at the next start."""
        left = self._deferred() + [folder]
        with open(os.path.join(self.dir, "delete-later.json"), "w", encoding="utf-8") as f:
            json.dump(sorted(set(left)), f)

    def _deferred(self):
        try:
            with open(os.path.join(self.dir, "delete-later.json"), encoding="utf-8") as f:
                return [p for p in json.load(f) if isinstance(p, str)]
        except (OSError, ValueError):
            return []

    def purge_deferred(self):
        import shutil
        base = os.path.realpath(os.path.join(self.dir, "data"))
        for p in self._deferred():
            if os.path.realpath(p).startswith(base + os.sep):          # only ever inside the apps' data folder
                shutil.rmtree(p, ignore_errors=True)
        try:
            os.remove(os.path.join(self.dir, "delete-later.json"))
        except OSError:
            pass

    def icon_path(self, aid):
        return os.path.join(self.dir, "icons", aid + ".png")

    def data_dir(self, aid):
        return os.path.join(self.dir, "data", aid)

    def get(self, aid):
        return self.apps.get(aid)

    def find_for_url(self, url):
        best = None
        for a in self.apps.values():
            if in_scope(url, a["scope"]) and (best is None or len(a["scope"]) > len(best["scope"])):
                best = a
        return best

    def add(self, manifest, name=None, auto_update=True):
        aid = app_id_for(manifest["start_url"])
        old = self.apps.get(aid, {})
        rec = {"id": aid, "name": (name or manifest["name"] or manifest["short_name"] or urlsplit(manifest["start_url"]).hostname or "App")[:60],
               "start_url": manifest["start_url"], "scope": manifest["scope"], "origin": origin_of(manifest["start_url"]),
               "display": manifest["display"], "theme_color": manifest["theme_color"], "background_color": manifest["background_color"],
               "manifest_url": manifest["manifest_url"], "fingerprint": fingerprint(manifest), "icons": manifest["icons"],
               "installed": old.get("installed") or time.time(), "updated": time.time(), "checked": time.time(),
               "auto_update": bool(old.get("auto_update", auto_update)), "shortcuts": old.get("shortcuts", [])}
        self.apps[aid] = rec
        self.save()
        return rec

    def apply_update(self, aid, manifest):
        a = self.apps[aid]
        a.update({"name": manifest["name"] or a["name"], "theme_color": manifest["theme_color"], "background_color": manifest["background_color"],
                  "display": manifest["display"], "icons": manifest["icons"], "fingerprint": fingerprint(manifest), "updated": time.time(),
                  "checked": time.time()})
        if manifest["scope"] and manifest["start_url"]:
            a["scope"], a["start_url"] = manifest["scope"], manifest["start_url"]
        self.save()
        return a

    def touch_checked(self, aid):
        if aid in self.apps:
            self.apps[aid]["checked"] = time.time()
            self.save()

    def remove(self, aid):
        self.apps.pop(aid, None)
        self.save()
        try:
            os.remove(self.icon_path(aid))
        except OSError:
            pass

    def public(self):
        return [{k: v for k, v in a.items() if k != "icons"} for a in sorted(self.apps.values(), key=lambda a: a["name"].lower())]
