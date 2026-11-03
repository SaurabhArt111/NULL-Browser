"""Installed web apps (PWAs) for BrowserApp: install, open, keep up to date, shortcuts, uninstall. Records and manifest rules: core/pwa.py."""
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time

from PyQt6.QtCore import QStandardPaths, QTimer, QUrl, Qt
from PyQt6.QtGui import QImage, QPainter, QColor, QPixmap, QFont
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineScript

from .core import crash, paths, pwa
from .core.accounts import GOOGLE_HOST, is_auth_cookie

log = logging.getLogger("null.pwa")
APP_WORLD = QWebEngineScript.ScriptWorldId.ApplicationWorld

# reads the page's manifest + icons; the result is parked on window.__nullPwa (runJavaScript does not wait for promises)
GATHER_JS = r"""(function(){
 window.__nullPwa = undefined;
 var l = document.querySelector('link[rel~="manifest"]');
 var meta = document.querySelector('meta[name="theme-color"]');
 var out = {title: document.title || '', url: location.href, theme: meta ? (meta.content || '') : '', manifestUrl: l ? l.href : '', text: '', icons: []};
 document.querySelectorAll('link[rel~="icon"],link[rel="apple-touch-icon"]').forEach(function(i){ out.icons.push({href: i.href, sizes: i.getAttribute('sizes') || ''}); });
 function done(){ window.__nullPwa = JSON.stringify(out); }
 if (!l) { done(); return 0; }
 fetch(l.href, {credentials: l.crossOrigin === 'use-credentials' ? 'include' : 'same-origin'}).then(function(r){ return r.text(); })
   .then(function(t){ out.text = t.slice(0, 200000); done(); }, function(){ done(); });
 return 0; })()"""
HAS_MANIFEST_JS = "!!document.querySelector('link[rel~=\"manifest\"]')"


def gather(page, callback, timeout_ms=6000):
    """Collect manifest info from a loaded page. callback(dict | None)."""
    state = {"t": 0, "done": False}

    def poll():
        if state["done"]:
            return
        state["t"] += 150
        page.runJavaScript("window.__nullPwa", APP_WORLD, got)

    def got(v):
        if state["done"]:
            return
        if isinstance(v, str):
            state["done"] = True
            try:
                callback(json.loads(v))
            except ValueError:
                callback(None)
        elif state["t"] >= timeout_ms:
            state["done"] = True
            callback(None)
        else:
            QTimer.singleShot(150, poll)

    page.runJavaScript(GATHER_JS, APP_WORLD, lambda _r: QTimer.singleShot(150, poll))


def contrast(hex_color):
    c = QColor(hex_color)
    if not c.isValid():
        return "#ffffff"
    return "#111111" if (0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()) > 160 else "#ffffff"


def letter_icon(text, color="#6c5ce7", size=256):
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(8, 8, size - 16, size - 16, size * 0.22, size * 0.22)
    f = QFont()
    f.setPixelSize(int(size * 0.5))
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor("#ffffff"))
    p.drawText(img.rect(), Qt.AlignmentFlag.AlignCenter, (text or "?")[:1].upper())
    p.end()
    return QPixmap.fromImage(img)


class PwaMixin:
    """Installed web apps."""

    def init_pwa(self):
        self.pwa = pwa.PwaStore(paths.sub("pwa"))
        self.pwa.purge_deferred()
        self.pwa_windows = {}
        self._pwa_profiles = {}
        self._pwa_net = None
        self._pwa_timer = QTimer(self, singleShot=True, interval=60_000, timeout=self._pwa_background_check)

    def pwa_start(self):
        if self.pwa.apps and not self.safe:
            self._pwa_timer.start()

    # ---- profiles ------------------------------------------------------------------------------
    def pwa_profile(self, aid):
        prof = self._pwa_profiles.get(aid)
        if prof is None:
            prof = self._make_profile(False, app_id=aid)
            self._pwa_profiles[aid] = prof
            rec = self.pwa.get(aid)
            if rec and GOOGLE_HOST.search(rec["origin"].split("://", 1)[-1].split(":")[0]) and self.keep_google_login():
                store = prof.cookieStore()                                # Google's own apps: the browser-level sign-in carries over
                for k, c in list(self.cookies.jar.items()):
                    if is_auth_cookie(k[2], k[0]):
                        store.setCookie(c)
        return prof

    # ---- install -------------------------------------------------------------------------------
    def can_install(self, tab):
        u = tab.page.url()
        return (not tab.private and u.scheme() in ("http", "https") and u.host() != "" and not tab.is_internal())

    def install_from_tab(self, tab, window):
        if not self.can_install(tab):
            window.show_toast("Only normal web pages can be installed as an app.")
            return
        existing = self.pwa.find_for_url(tab.page.url().toString())
        if existing:
            self.open_pwa(existing["id"])
            return
        gather(tab.page, lambda info: self._install_step2(tab, window, info))

    def _install_step2(self, tab, window, info):
        if info is None:
            info = {"title": tab.page.title(), "url": tab.page.url().toString(), "theme": "", "manifestUrl": "", "text": "", "icons": []}
        m = pwa.parse_manifest(info["text"], info["manifestUrl"], info["url"])
        if not m["name"]:
            m["name"] = (info["title"] or tab.page.url().host())[:60]
        if not m["theme_color"] and info.get("theme"):
            m["theme_color"] = pwa._color(info["theme"])
        if not m["icons"]:
            for ic in info.get("icons", []):
                sizes = [int(x) for x in re.findall(r"(\d+)x\d+", ic.get("sizes") or "")]
                m["icons"].append({"src": ic["href"], "size": max(sizes) if sizes else 0, "purpose": "any"})
        fallback = tab.page.icon().pixmap(128, 128) if not tab.page.icon().isNull() else None
        self.fetch_pwa_icon(m, fallback, lambda pm: self._install_dialog(window, m, pm))

    def fetch_pwa_icon(self, manifest, fallback, done):
        """Download the manifest's best icon; fall back to the page's favicon, then to a drawn letter."""
        choice = pwa.best_icon(manifest["icons"])

        def use(pm):
            if pm is None or pm.isNull():
                pm = fallback if (fallback is not None and not fallback.isNull()) else letter_icon(manifest["name"])
            done(pm)
        if not choice:
            use(None)
            return
        if self._pwa_net is None:
            self._pwa_net = QNetworkAccessManager(self)
        req = QNetworkRequest(QUrl(choice["src"]))
        req.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute, QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        req.setTransferTimeout(8000)
        reply = self._pwa_net.get(req)

        def finished():
            pm = None
            try:
                if reply.error() == QNetworkReply.NetworkError.NoError:
                    data = bytes(reply.readAll())
                    if len(data) < 3_000_000:
                        pm = QPixmap()
                        if not pm.loadFromData(data):
                            pm = None
            finally:
                reply.deleteLater()
            use(pm)
        reply.finished.connect(finished)

    def _install_dialog(self, window, manifest, pm):
        from .ui.pwa_install import InstallDialog
        dlg = InstallDialog(window, manifest, pm)
        if not dlg.exec():
            return
        rec = self.pwa.add(manifest, dlg.name(), auto_update=dlg.auto_update())
        self.save_pwa_icon(rec["id"], pm)
        self.create_shortcuts(rec["id"], desktop=dlg.want_desktop(), menu=dlg.want_menu())
        self.open_pwa(rec["id"])
        window.show_toast(f"Installed “{rec['name']}”. It keeps its own sign-ins and data, separate from the browser.")
        self.pwaChanged.emit()

    def save_pwa_icon(self, aid, pm):
        pm.scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation).save(self.pwa.icon_path(aid), "PNG")

    # ---- open ----------------------------------------------------------------------------------
    @crash.guarded
    def open_pwa(self, aid, url=None):
        rec = self.pwa.get(aid)
        if rec is None:
            log.warning("unknown app %s", aid)
            return None
        w = self.pwa_windows.get(aid)
        if w is not None:
            w.show()
            w.raise_()
            w.activateWindow()
            if url:
                w.tab.load(url)
            return w
        from .ui.pwa_window import PwaWindow
        w = PwaWindow(self, rec, url)
        self.pwa_windows[aid] = w
        w.destroyed.connect(lambda *_: self.pwa_windows.pop(aid, None))
        w.show()
        return w

    # ---- updates -------------------------------------------------------------------------------
    def pwa_check_update(self, aid, page, force=False, callback=None):
        """Compare the site's current manifest with the installed one; apply changes. With force: also drop the app's HTTP cache,
        ask its service workers to update and reload. callback(str) gets a one-line result."""
        rec = self.pwa.get(aid)
        if rec is None:
            return

        def got(info):
            note = "Could not reach the app. It will try again later."
            if info is not None:
                m = pwa.parse_manifest(info["text"], info["manifestUrl"], info["url"])
                if not m["theme_color"] and info.get("theme"):
                    m["theme_color"] = pwa._color(info["theme"])
                if info["manifestUrl"] and pwa.fingerprint(m) != rec.get("fingerprint") and pwa.origin_of(m["start_url"]) == rec["origin"]:
                    self.pwa.apply_update(aid, m)
                    note = "Updated: the site changed its app details."
                    self.fetch_pwa_icon(m, None, lambda pm: (self.save_pwa_icon(aid, pm), self.pwaChanged.emit()))
                    w = self.pwa_windows.get(aid)
                    if w:
                        w.refresh_identity()
                else:
                    self.pwa.touch_checked(aid)
                    note = "Up to date."
            if force:
                prof = page.profile()
                prof.clearHttpCache()
                page.runJavaScript("navigator.serviceWorker&&navigator.serviceWorker.getRegistrations().then(function(r){r.forEach(function(x){x.update();});});0",
                                   APP_WORLD)
                QTimer.singleShot(400, lambda: page.triggerAction(QWebEnginePage.WebAction.ReloadAndBypassCache))
                note += " Fetched the latest files."
            self.pwaChanged.emit()
            if callback:
                callback(note)
        gather(page, got)

    def pwa_check_update_headless(self, aid, callback=None):
        """Check without a window: load the app's start page in a hidden page of its own profile."""
        rec = self.pwa.get(aid)
        if rec is None:
            return
        w = self.pwa_windows.get(aid)
        if w is not None:
            self.pwa_check_update(aid, w.tab.page, force=True, callback=callback)
            return
        page = QWebEnginePage(self.pwa_profile(aid), self)
        finished = {"v": False}

        def done(note):
            if not finished["v"]:
                finished["v"] = True
                QTimer.singleShot(1500, page.deleteLater)
                if callback:
                    callback(note)

        def loaded(ok):
            if ok:
                self.pwa_check_update(aid, page, force=False, callback=done)
            else:
                done("Could not reach the app.")
        page.loadFinished.connect(loaded)
        QTimer.singleShot(20000, lambda: done("Timed out."))
        page.load(QUrl(rec["start_url"]))

    def _pwa_background_check(self):
        """Once per start, a minute in: refresh apps that have not been checked for a while (only those with auto-update on)."""
        hours = max(1, int(self.settings.get("pwa_update_hours") or 12))
        for rec in list(self.pwa.apps.values()):
            if rec.get("auto_update") and time.time() - rec.get("checked", 0) > hours * 3600 and rec["id"] not in self.pwa_windows:
                self.pwa_check_update_headless(rec["id"])
                return                                                  # one per tick, spaced out
        QTimer.singleShot(0, lambda: None)

    # ---- shortcuts -----------------------------------------------------------------------------
    def _launch_command(self, aid):
        if getattr(sys, "frozen", False):
            return sys.executable, ["--app", aid], ""
        exe = sys.executable
        if sys.platform.startswith("win"):
            pw = os.path.join(os.path.dirname(exe), "pythonw.exe")
            exe = pw if os.path.isfile(pw) else exe
        return exe, ["-m", "null_browser", "--app", aid], os.path.dirname(paths.package_dir())

    def create_shortcuts(self, aid, desktop=True, menu=True):
        rec = self.pwa.get(aid)
        if rec is None:
            return []
        made = []
        try:
            exe, args, cwd = self._launch_command(aid)
            icon = self.pwa.icon_path(aid)
            name = "".join(ch for ch in rec["name"] if ch not in '<>:"/\\|?*').strip() or aid
            dirs = []
            if desktop:
                dirs.append(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation))
            if menu:
                if sys.platform.startswith("win"):
                    dirs.append(os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", "Null Browser Apps"))
                elif sys.platform != "darwin":
                    dirs.append(os.path.join(os.path.expanduser("~"), ".local", "share", "applications"))
            for d in [x for x in dirs if x]:
                os.makedirs(d, exist_ok=True)
                if sys.platform.startswith("win"):
                    path = os.path.join(d, name + ".lnk")
                    ico = os.path.join(paths.sub("pwa", "icons"), aid + ".ico")
                    ico_ok = QImage(icon).scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation).save(ico, "ICO")
                    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');$s.TargetPath='%s';$s.Arguments='%s';$s.WorkingDirectory='%s';%s$s.Save()"
                          % (path.replace("'", "''"), exe.replace("'", "''"), " ".join(args).replace("'", "''"), cwd.replace("'", "''"),
                             ("$s.IconLocation='%s';" % ico.replace("'", "''")) if ico_ok else ""))
                    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], timeout=20, capture_output=True,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                elif sys.platform != "darwin":
                    path = os.path.join(d, f"null-app-{aid}.desktop")
                    cmd = " ".join(f'"{a}"' if " " in a else a for a in [exe] + args)
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(f"[Desktop Entry]\nType=Application\nName={rec['name']}\nExec={cmd}\nIcon={icon}\nTerminal=false\n"
                                f"Categories=Network;WebBrowser;\nStartupWMClass=null-app-{aid}\n" + (f"Path={cwd}\n" if cwd else ""))
                    os.chmod(path, 0o755)
                else:
                    continue
                if os.path.exists(path):
                    made.append(path)
        except Exception:
            log.exception("creating shortcuts")
        rec["shortcuts"] = sorted(set(rec.get("shortcuts", [])) | set(made))
        self.pwa.save()
        return made

    def remove_shortcuts(self, aid):
        rec = self.pwa.get(aid)
        for p in (rec or {}).get("shortcuts", []):
            try:
                os.remove(p)
            except OSError:
                pass

    # ---- data / uninstall ----------------------------------------------------------------------
    def clear_pwa_data(self, aid):
        """Wipe one app's cookies, storage and cache (not the app itself)."""
        prof = self._pwa_profiles.get(aid)
        if prof is not None:
            prof.cookieStore().deleteAllCookies()
            prof.clearHttpCache()
        w = self.pwa_windows.get(aid)
        if w:
            w.tab.reload()
        base = self.pwa.data_dir(aid)
        for sub in ("storage",):
            for name in ("Local Storage", "IndexedDB", "Session Storage", "Service Worker", "File System", "databases", "shared_proto_db"):
                shutil.rmtree(os.path.join(base, sub, name), ignore_errors=True)       # may be in use: Chromium recreates what it needs

    def uninstall_pwa(self, aid, delete_data=True):
        w = self.pwa_windows.pop(aid, None)
        if w:
            w.close()
        self.remove_shortcuts(aid)
        prof = self._pwa_profiles.pop(aid, None)
        if prof is not None:
            try:
                prof.cookieStore().deleteAllCookies()
                prof.clearHttpCache()
            except Exception:
                pass
            QTimer.singleShot(1000, prof.deleteLater)
        if delete_data:
            self._delete_app_folder(self.pwa.data_dir(aid))
        self.pwa.remove(aid)
        self.pwaChanged.emit()

    def _delete_app_folder(self, folder):
        """The app's profile may still hold files open for a moment (Windows refuses to delete them): retry once the profile is gone,
        and if the folder is still there, remember it and finish at the next start (before any profile exists)."""
        shutil.rmtree(folder, ignore_errors=True)
        if not os.path.isdir(folder):
            return

        def retry():
            shutil.rmtree(folder, ignore_errors=True)
            if os.path.isdir(folder):
                self.pwa.defer_delete(folder)
        QTimer.singleShot(3000, retry)
