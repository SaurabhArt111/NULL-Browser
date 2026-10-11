"""BrowserApp: owns profiles, policies, windows, session and every shared service."""
import json
import logging
import os
import platform
import re
import shutil
import sys
import time

from PyQt6.QtCore import QObject, QTimer, QUrl, QT_VERSION_STR, PYQT_VERSION_STR, Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWebEngineCore import (QWebEnginePage, QWebEngineProfile, QWebEngineScript, QWebEngineSettings,
                                   qWebEngineChromiumVersion)
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import constants as C
from .core import crash, paths
from .core.adblock import AdBlocker
from .core.db import Database
from .core.downloads import DownloadManager
from .core.engine_service import EngineService
from .core.notify import Notifier
from .core.permissions import PermissionManager, SHIM_FEATURES, origin_of
from .core.search import SearchManager, SuggestClient
from .core.settings import Settings
from .ui import icons, native, theme
from .web.scheme import NullSchemeHandler

log = logging.getLogger("null.app")
WA = QWebEngineSettings.WebAttribute
SHIM_NAME = "null-shim"
STORAGE_DIRS = ("Local Storage", "IndexedDB", "Session Storage", "Service Worker", "File System", "databases", "shared_proto_db")


def ipc_name():
    import getpass
    import hashlib
    try:
        user = getpass.getuser()
    except Exception:
        user = "user"
    tag = hashlib.sha1(paths.data_dir().encode()).hexdigest()[:8]
    return f"NullBrowser-{re.sub(r'[^A-Za-z0-9_-]', '_', user)}-{tag}"


def forward_to_running_instance(urls, private):
    """If another Null Browser is already running on this profile, hand it the URLs and return True."""
    sock = QLocalSocket()
    sock.connectToServer(ipc_name())
    if not sock.waitForConnected(400):
        return False
    sock.write(json.dumps({"urls": urls, "private": private}).encode() + b"\n")
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    return True


class BrowserApp(QObject):
    themeChanged = pyqtSignal()

    def __init__(self, qapp, safe_mode=False, start_private=False):
        super().__init__(qapp)
        self.qapp = qapp
        self.safe = safe_mode
        self.windows = []
        self.cert_allow = set()
        self.closed_tabs = []                 # recently closed tabs (url, title) across windows
        self._shutting_down = False
        self._private_profile = None
        self._icon_cache = {}

        self._apply_pending_clear()
        self.settings = Settings()
        self.db = Database()
        self.perms = PermissionManager(self.db, self.settings)
        self.search = SearchManager(self.settings)
        self.adblock = AdBlocker(self.settings, self.perms, self)
        self.engine = EngineService(self.settings, self)
        self.tray = QSystemTrayIcon(icons.app_icon(), self)
        self.tray.setToolTip(C.APP_NAME)
        self.notifier = Notifier(self.tray, self.settings)
        self.downloads = DownloadManager(self.db, self.settings, self.perms, self.notifier, self)
        self.downloads.parent_window = self.active_window
        self.palette_colors = theme.resolve(self.settings.get("theme"))

        self.profile = self._make_profile(private=False)
        self.perms.on_change = self.refresh_shim
        self.settings.changed.connect(self.on_setting_changed)
        crash.bus.too_many.connect(self._error_storm)
        crash.bus.error.connect(self._error_toast)
        self._build_tray()
        self.apply_theme()

        self.mem_timer = QTimer(self, interval=60_000)
        self.mem_timer.timeout.connect(self.memory_saver_tick)
        self.mem_timer.start()
        self.session_timer = QTimer(self, interval=20_000)
        self.session_timer.timeout.connect(self.save_session)
        self.session_timer.start()
        self.qapp.setQuitOnLastWindowClosed(not self.settings.get("background_running"))
        self.qapp.aboutToQuit.connect(self.shutdown)
        self.qapp.commitDataRequest.connect(lambda mgr: self.save_session()) if hasattr(self.qapp, "commitDataRequest") else None

        self.server = None
        self._lock_file = os.path.join(paths.data_dir(), "running.lock")
        self.crashed_last_time = os.path.exists(self._lock_file)
        try:
            with open(self._lock_file, "w") as f:
                f.write(str(os.getpid()))
        except OSError:
            pass
        self.start_private = start_private

    # ------------------------------------------------------------------ versions / info
    def versions(self):
        return {
            "Null Browser": C.VERSION, "Chromium engine": qWebEngineChromiumVersion(), "Qt": QT_VERSION_STR,
            "PyQt": PYQT_VERSION_STR, "Python": platform.python_version(), "OS": f"{platform.system()} {platform.release()}",
            "User agent": self.profile.httpUserAgent(), "Profile path": paths.data_dir(),
            "Mode": "Safe mode" if self.safe else "Normal",
        }

    def active_window(self):
        w = self.qapp.activeWindow()
        if w in self.windows:
            return w
        return self.windows[-1] if self.windows else None

    # ------------------------------------------------------------------ API used by the window / tab code
    @property
    def accent(self):
        return self.settings.get("accent") or "#6c5ce7"

    def pal(self, private=False):
        return theme.resolve(self.settings.get("theme"), private)

    def icon(self, name, color=None, size=20, private=False):
        p = self.pal(private)
        col = color or p["text"]
        key = (name, col, size, p["muted"])
        ic = self._icon_cache.get(key)
        if ic is None:
            ic = icons.icon(name, col, size, p["muted"])
            self._icon_cache[key] = ic
        return ic

    def profile_for(self, private):
        return self.private_profile if private else self.profile

    def open_window(self, url=None, private=False):
        return self.new_window(private=bool(private), url=url)

    def quit_all(self):
        self.quit()

    def window_closing(self, win):
        if win in self.windows:
            self.windows.remove(win)
        if not win.private:
            self.save_session()
        QTimer.singleShot(0, self.maybe_drop_private_profile)

    # ------------------------------------------------------------------ profiles
    def _make_profile(self, private):
        if private:
            prof = QWebEngineProfile(self)                      # unnamed profile == off the record
            prof.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
        else:
            prof = QWebEngineProfile("NullBrowser", self)
            prof.setPersistentStoragePath(paths.sub("profile", "storage"))
            prof.setCachePath(paths.sub("profile", "cache"))
            prof.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)
            prof.setHttpCacheMaximumSize(300 * 1024 * 1024)
            prof.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies)
        try:
            prof.setPersistentPermissionsPolicy(QWebEngineProfile.PersistentPermissionsPolicy.AskEveryTime)
        except Exception:
            pass
        ua = re.sub(r"\s*QtWebEngine/[\d.]+", "", prof.httpUserAgent())
        prof.setHttpUserAgent(f"{ua} {C.UA_TOKEN}")
        prof.setHttpAcceptLanguage(self.settings.get("accept_languages") or "en-US,en")
        try:
            prof.setSpellCheckEnabled(bool(self.settings.get("spellcheck")))
        except Exception:
            pass
        handler = NullSchemeHandler(self, private=private, parent=prof)
        prof.installUrlSchemeHandler(C.SCHEME.encode(), handler)
        if not self.safe:
            prof.setUrlRequestInterceptor(self.adblock)
        prof.downloadRequested.connect(lambda req, p=private: self.downloads.handle(req, p))
        prof.setNotificationPresenter(self.notifier.present_web)
        prof.cookieStore().setCookieFilter(self._cookie_filter)
        self._install_shim(prof, private)
        return prof

    @property
    def private_profile(self):
        if self._private_profile is None:
            self._private_profile = self._make_profile(private=True)
        return self._private_profile

    def _cookie_filter(self, req):
        try:
            first = req.firstPartyUrl()
            if first.scheme() not in ("http", "https"):
                return True
            v = self.perms.effective(origin_of(first.toString()), "cookies")
            if v == "block":
                return False
            if v == "block_third" and req.thirdParty:
                return False
        except Exception:
            pass
        return True

    def maybe_drop_private_profile(self):
        if self._private_profile is None or any(w.private for w in self.windows):
            return
        prof, self._private_profile = self._private_profile, None
        self.perms.session.clear()
        QTimer.singleShot(800, lambda: prof.deleteLater())

    # ------------------------------------------------------------------ windows
    def new_window(self, private=False, url=None, show=True):
        from .ui.window import MainWindow
        w = MainWindow(self, private=private)
        self.windows.append(w)
        w.destroyed.connect(lambda *_: self._window_gone(w))
        if url:
            w.add_tab(url)
        elif show:
            w.add_tab("null://newtab")
        if show:
            w.show()
            w.raise_()
            w.activateWindow()
        return w

    def _window_gone(self, w):
        if w in self.windows:
            self.windows.remove(w)
        self.maybe_drop_private_profile()

    def open_urls(self, urls, private=False):
        w = self.active_window()
        if w is None or (private and not w.private):
            w = self.new_window(private=private, show=True) if not urls else self.new_window(private=private, url=urls[0])
            urls = urls[1:]
        for u in urls:
            w.add_tab(u)
        w.show()
        w.setWindowState(w.windowState() & ~Qt.WindowState.WindowMinimized)
        w.raise_()
        w.activateWindow()

    # ------------------------------------------------------------------ startup / single instance
    def ipc_name(self):
        return ipc_name()

    def listen_for_instances(self):
        name = self.ipc_name()
        QLocalServer.removeServer(name)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if not self.server.listen(name):
            log.warning("single-instance server failed: %s", self.server.errorString())
            return
        self.server.newConnection.connect(self._ipc_connection)

    def _ipc_connection(self):
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            sock.readyRead.connect(lambda s=sock: self._ipc_read(s))
            sock.disconnected.connect(sock.deleteLater)

    @crash.guarded
    def _ipc_read(self, sock):
        for line in bytes(sock.readAll()).splitlines():
            try:
                msg = json.loads(line.decode())
            except ValueError:
                continue
            urls = [u for u in msg.get("urls", []) if isinstance(u, str)][:20]
            self.open_urls(urls, bool(msg.get("private")))

    def start(self, urls, private=False):
        """Open the first window(s) according to startup settings."""
        self.listen_for_instances()
        if self.settings.get("autostart_null_search"):
            QTimer.singleShot(400, self.engine.start)
        mode = self.settings.get("startup_mode")
        restored = False
        if urls or private:
            self.new_window(private=private, url=urls[0] if urls else None)
            for u in urls[1:]:
                self.windows[-1].add_tab(u)
        elif mode == "continue" and not self.safe:
            restored = self.restore_session()
        elif mode == "urls" and self.settings.get("startup_urls"):
            su = self.settings.get("startup_urls")
            self.new_window(url=su[0])
            for u in su[1:]:
                self.windows[-1].add_tab(u)
        if not self.windows:
            self.new_window()
        w = self.windows[0]
        if self.safe:
            w.add_infobar("Safe mode is on: ad blocking, the site-API gate and session restore are switched off.",
                          [("Relaunch normally", lambda: self.restart(safe=False))])
        elif self.crashed_last_time and not restored and mode != "continue" and self._has_saved_session():
            w.add_infobar("Null Browser didn't shut down correctly last time.",
                          [("Restore tabs", self.restore_session), ("Dismiss", lambda: None)])
        QTimer.singleShot(6000, crash.mark_startup_ok)

    # ------------------------------------------------------------------ session
    def _session_file(self):
        return os.path.join(paths.data_dir(), "session.json")

    def _has_saved_session(self):
        try:
            with open(self._session_file(), encoding="utf-8") as f:
                return any(w.get("tabs") for w in json.load(f).get("windows", []))
        except (OSError, ValueError):
            return False

    @crash.guarded(quiet=True)
    def save_session(self):
        if self._shutting_down and not self.windows:
            return
        data = {"windows": [w.session_state() for w in self.windows if not w.private and w.tabs]}
        if not data["windows"]:
            return
        tmp = self._session_file() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, self._session_file())

    def restore_session(self):
        try:
            with open(self._session_file(), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return False
        made = False
        for ws in data.get("windows", []):
            entries = [t for t in ws.get("tabs", []) if isinstance(t.get("url"), str)]
            if not entries:
                continue
            w = self.new_window(show=False)
            w.restore_state(ws)
            w.show()
            made = True
        return made

    # ------------------------------------------------------------------ theme / icons
    def apply_theme(self):
        theme.apply_color_scheme(self.settings.get("theme"))
        self.palette_colors = theme.resolve(self.settings.get("theme"))
        accent = self.settings.get("accent")
        self.qapp.setPalette(theme.palette(self.palette_colors, accent))
        self.qapp.setStyleSheet(theme.stylesheet(self.palette_colors, accent))
        self._icon_cache.clear()
        self.themeChanged.emit()

    # ------------------------------------------------------------------ page settings & policies
    def apply_page_settings(self, page):
        s, st = page.settings(), self.settings
        s.setFontSize(QWebEngineSettings.FontSize.DefaultFontSize, int(st.get("font_size") or 16))
        s.setFontSize(QWebEngineSettings.FontSize.MinimumFontSize, int(st.get("min_font_size") or 0))
        s.setAttribute(WA.ForceDarkMode, bool(st.get("web_dark_mode")))
        s.setAttribute(WA.ScrollAnimatorEnabled, bool(st.get("smooth_scrolling")))
        s.setAttribute(WA.PlaybackRequiresUserGesture, self.perms.default("autoplay") == "block")
        s.setAttribute(WA.JavascriptCanAccessClipboard, True)
        s.setAttribute(WA.JavascriptCanPaste, True)

    def all_tabs(self):
        for w in list(self.windows):
            yield from list(w.tabs)

    def apply_site_policy(self, tab, url):
        page, s = tab.page, tab.page.settings()
        scheme = url.scheme()
        if scheme in (C.SCHEME, "about", "file", "qrc", "data", "view-source", "devtools", "chrome-devtools") or not url.host():
            s.setAttribute(WA.JavascriptEnabled, True)
            s.setAttribute(WA.AutoLoadImages, True)
            s.setAttribute(WA.AllowRunningInsecureContent, False)
            page.setAudioMuted(tab.user_muted)
            return
        origin = origin_of(url.toString())
        eff = lambda f: self.perms.effective(origin, f, tab.private)
        s.setAttribute(WA.JavascriptEnabled, eff("javascript") == "allow")
        s.setAttribute(WA.AutoLoadImages, eff("images") == "allow")
        s.setAttribute(WA.AllowRunningInsecureContent, eff("insecure_content") == "allow")
        page.setAudioMuted(tab.user_muted or eff("sound") == "mute")

    def _install_shim(self, profile, private):
        """One profile-level script carries the whole permission table and looks up its row by location.origin."""
        coll = profile.scripts()
        for sc in coll.find(SHIM_NAME):
            coll.remove(sc)
        if self.safe:
            return
        sc = QWebEngineScript()
        sc.setName(SHIM_NAME)
        sc.setSourceCode(self.perms.shim_source(private))
        sc.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        sc.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        sc.setRunsOnSubFrames(True)
        coll.insert(sc)

    def refresh_shim(self):
        for prof, private in ((self.profile, False), (self._private_profile, True)):
            if prof is not None:
                try:
                    self._install_shim(prof, private)
                except Exception:
                    log.exception("refreshing the API gate")

    def apply_site_policies(self):
        """Re-evaluate every open tab after a permission change."""
        for t in self.all_tabs():
            try:
                self.apply_site_policy(t, t.page.url())
                t.securityChanged.emit()
            except Exception:
                log.exception("re-applying policy")

    def apply_global_policies(self):
        for t in self.all_tabs():
            self.apply_page_settings(t.page)
        self.apply_site_policies()

    def apply_zoom(self, tab):
        host = tab.page.url().host()
        z = self.db.get_zoom(host) if host else None
        if z is None:
            z = (self.settings.get("default_zoom") or 100) / 100.0
        if abs(tab.page.zoomFactor() - z) > 0.001:
            tab.page.setZoomFactor(z)
            tab.zoomChanged.emit()

    # ------------------------------------------------------------------ settings reactions
    @crash.guarded
    def on_setting_changed(self, key):
        v = self.settings.get(key)
        if key in ("theme", "accent"):
            self.apply_theme()
        elif key in ("adblock", "block_trackers", "send_dnt"):
            self.adblock.refresh()
            self.refresh_shield()
        elif key in ("font_size", "min_font_size", "web_dark_mode", "smooth_scrolling"):
            for t in self.all_tabs():
                self.apply_page_settings(t.page)
        elif key == "default_zoom":
            for t in self.all_tabs():
                self.apply_zoom(t)
        elif key in ("show_bookmarks_bar", "show_home_button"):
            for w in self.windows:
                w.refresh_chrome()
        elif key == "background_running":
            self.qapp.setQuitOnLastWindowClosed(not v)
            self.tray.setVisible(bool(v))
        elif key == "spellcheck":
            for p in (self.profile, self._private_profile):
                if p:
                    try:
                        p.setSpellCheckEnabled(bool(v))
                    except Exception:
                        pass
        elif key == "accept_languages":
            for p in (self.profile, self._private_profile):
                if p:
                    p.setHttpAcceptLanguage(v or "en-US,en")
        elif key == "autostart_null_search" and v and self.engine.state == "stopped":
            self.engine.start()

    def bookmarks_changed(self):
        for w in self.windows:
            w.refresh_bookmarks()
            w.update_star()

    def refresh_shield(self):
        for w in self.windows:
            w.refresh_shield()

    # ------------------------------------------------------------------ privacy
    def _pending_file(self):
        return os.path.join(paths.data_dir(), "pending-clear.json")

    def _apply_pending_clear(self):
        """Runs before any WebEngine profile exists, so site storage dirs are unlocked."""
        try:
            if os.path.exists(self._pending_file()):
                os.remove(self._pending_file())
                base = paths.sub("profile", "storage")
                for d in STORAGE_DIRS:
                    shutil.rmtree(os.path.join(base, d), ignore_errors=True)
                log.info("Cleared local site storage")
        except Exception:
            log.exception("pending clear failed")

    def clear_data(self, types, rng="all"):
        seconds = {"hour": 3600, "day": 86400, "week": 7 * 86400, "month": 28 * 86400}.get(rng)
        start = time.time() - seconds if seconds else 0
        if "history" in types:
            self.db.delete_history_range(start)
            self.profile.clearAllVisitedLinks()
        if "downloads" in types:
            self.db.run("DELETE FROM downloads WHERE state<>'in_progress' AND started>=?", (start,))
            self.downloads.clear_finished() if not seconds else None
            self.downloads.changed.emit()
        if "cache" in types:
            self.profile.clearHttpCache()
            if self._private_profile:
                self._private_profile.clearHttpCache()
        if "cookies" in types:
            self.profile.cookieStore().deleteAllCookies()
            if self._private_profile:
                self._private_profile.cookieStore().deleteAllCookies()
            try:
                with open(self._pending_file(), "w") as f:
                    f.write("1")
            except OSError:
                pass
        if "site_perms" in types:
            self.perms.reset_all_sites()
            self.apply_site_policies()
        log.info("Cleared browsing data: %s (%s)", sorted(types), rng)

    # ------------------------------------------------------------------ memory saver
    @crash.guarded(quiet=True)
    def memory_saver_tick(self):
        if not self.settings.get("memory_saver"):
            return
        limit = max(1, int(self.settings.get("memory_saver_minutes") or 15)) * 60
        now = time.time()
        for t in self.all_tabs():
            if (now - t.last_active > limit and not t.pinned and not t.loading and not t.discarded
                    and not t.page.recentlyAudible() and t.devtools is None and not t.is_internal()):
                t.discard()

    # ------------------------------------------------------------------ tray
    def _build_tray(self):
        m = QMenu()
        m.addAction("New window", lambda: self.new_window())
        m.addAction("New InPrivate window", lambda: self.new_window(private=True))
        m.addAction("Downloads", lambda: self.open_urls(["null://downloads"]))
        m.addSeparator()
        m.addAction("Quit", self.quit)
        self._tray_menu = m
        self.tray.setContextMenu(m)
        self.tray.activated.connect(lambda r: self.open_urls([]) if r == QSystemTrayIcon.ActivationReason.Trigger else None)
        if self.settings.get("background_running"):
            self.tray.show()

    # ------------------------------------------------------------------ errors
    def _error_toast(self, msg):
        w = self.active_window()
        if w:
            w.show_toast(f"Something went wrong and was handled: {msg[:120]}")

    def _error_storm(self):
        w = self.active_window()
        if w:
            w.offer_safe_mode()

    # ------------------------------------------------------------------ lifecycle
    def restart(self, safe=False):
        self._shutting_down = True
        crash.restart_app(["--safe-mode"] if safe else None)
        self.qapp.quit()

    def quit(self):
        self.qapp.setQuitOnLastWindowClosed(True)
        self.qapp.quit()

    @crash.guarded(quiet=True)
    def shutdown(self):
        if self._shutting_down and not self.windows:
            return
        self._shutting_down = True
        self.save_session()
        for key in self.settings.get("clear_on_exit") or []:
            try:
                self.clear_data({key}, "all")
            except Exception:
                log.exception("clear on exit")
        try:
            self.engine.stop()
        except Exception:
            pass
        self.db.close()
        try:
            os.remove(self._lock_file)
        except OSError:
            pass
        crash.mark_startup_ok()
        log.info("Clean shutdown")
