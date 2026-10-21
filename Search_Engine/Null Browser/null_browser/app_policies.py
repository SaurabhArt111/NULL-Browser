"""Settings / policy propagation for BrowserApp."""
import json
import logging
import re

from PyQt6.QtNetwork import QLocalSocket
from PyQt6.QtWebEngineCore import (QWebEngineScript, QWebEngineSettings)

from . import constants as C
from .core import paths
from .core.permissions import origin_of
from .ui import theme

log = logging.getLogger("null.app")
WA = QWebEngineSettings.WebAttribute
SHIM_NAME = "null-shim"


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


class PoliciesMixin:
    """Theme, page settings, per-site policy, the permission shim and zoom."""

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

    def _permissions_changed(self):
        self.cookie_policy.invalidate()
        self.refresh_shim()

    def refresh_shim(self):
        for prof, private in ((self.profile, False), (self._private_profile, True)):
            if prof is not None:
                try:
                    self._install_shim(prof, private)
                except Exception:
                    log.exception("refreshing the API gate")

    def refresh_video(self):
        """Settings for the H.264 bridge changed: re-detect ffmpeg, replace the page script, (un)expose the bridge on open pages."""
        self.video.refresh()
        for prof in (self.profile, self._private_profile):
            if prof is not None:
                try:
                    self.video.install_script(prof)
                except Exception:
                    log.exception("refreshing the video bridge")
        for t in self.all_tabs():
            try:
                self.video.attach(t.page)
            except Exception:
                log.exception("attaching the video bridge")

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
