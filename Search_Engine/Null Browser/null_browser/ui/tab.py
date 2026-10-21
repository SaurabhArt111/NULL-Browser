"""A browser tab: page + view + overlays (find bar, permission prompts, hover status, DevTools)."""
import logging
import time
from urllib.parse import parse_qs, quote

from PyQt6.QtCore import QBuffer, QIODevice, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices
from PyQt6.QtWebEngineCore import QWebEngineLoadingInfo, QWebEnginePage, QWebEngineSettings
from PyQt6.QtWidgets import (QLabel, QMessageBox, QSplitter, QVBoxLayout, QWidget)

from ..constants import SCHEME
from ..core import crash
from ..core.permissions import origin_of
from .findbar import FindBar
from .page import BrowserPage, WebView
from .permission_bubble import PermissionBubble
from .tab_devtools import DevToolsMixin
from .tab_menu import ContextMenuMixin
from .tab_permissions import PermissionsMixin
from .tab_tools import PageToolsMixin

log = logging.getLogger("null.tab")
WA = QWebEngineSettings.WebAttribute
LS = QWebEngineLoadingInfo.LoadStatus
ED = QWebEngineLoadingInfo.ErrorDomain


class Tab(ContextMenuMixin, DevToolsMixin, PermissionsMixin, PageToolsMixin, QWidget):
    """One browser tab. Behaviour is split over the mixins: context menu, DevTools, permissions / auth, page tools."""
    titleChanged = pyqtSignal(object)
    urlChanged = pyqtSignal(object)
    iconChanged = pyqtSignal(object)
    loadingChanged = pyqtSignal(bool)
    progressChanged = pyqtSignal(int)
    audioChanged = pyqtSignal()
    securityChanged = pyqtSignal()
    zoomChanged = pyqtSignal()
    popupBlocked = pyqtSignal()
    openTab = pyqtSignal(str, bool, object)         # url, background, request-or-None
    openWindow = pyqtSignal(str, bool)              # url, private
    closeRequested = pyqtSignal(object)
    fullscreenToggled = pyqtSignal(bool)
    focusOmnibox = pyqtSignal()

    def __init__(self, app, profile, private=False, parent=None):
        super().__init__(parent)
        self.app, self.profile, self.private = app, profile, private
        self.pinned = False
        self.user_muted = False
        self.loading = False
        self.progress = 0
        self.http_fallback = ""             # http:// retry URL for https-first
        self.typed_url = ""
        self.blocked_popups = 0
        self.last_active = time.time()
        self.devtools = None
        self.devtools_host = None
        self.current_origin = ""
        self.discarded = False
        self.cert_failed = False
        self._last_history_url = ""
        self._upgraded = False
        self.lazy_url = ""                 # restored-session tab that has not been loaded yet
        self.lazy_title = ""

        self.page = BrowserPage(profile, self)
        self.view = WebView(self)
        self.view.setPage(self.page)
        self.split = QSplitter(Qt.Orientation.Horizontal, self)
        self.split.setChildrenCollapsible(False)
        self.split.addWidget(self.view)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.split)

        self.find = FindBar(self)
        self.find.hide()
        self.bubble = PermissionBubble(self)
        self.bubble.hide()
        self.hover = QLabel(self)
        self.hover.setObjectName("hoverstatus")
        self.hover.hide()

        self._configure_settings()
        self._wire()
        self.app.themeChanged.connect(self._restyle_devtools)
        self.app.themeChanged.connect(self.refresh_background)
        self.refresh_background()

    # ---- setup ----------------------------------------------------------------------
    def _configure_settings(self):
        s = self.page.settings()
        for attr, val in ((WA.ErrorPageEnabled, False), (WA.FullScreenSupportEnabled, True), (WA.JavascriptCanOpenWindows, True),
                          (WA.PluginsEnabled, True), (WA.PdfViewerEnabled, True), (WA.ScreenCaptureEnabled, True),
                          (WA.WebGLEnabled, True), (WA.LocalStorageEnabled, True), (WA.FocusOnNavigationEnabled, True),
                          (WA.AllowWindowActivationFromJavaScript, False), (WA.HyperlinkAuditingEnabled, False),
                          (WA.LocalContentCanAccessRemoteUrls, False), (WA.LocalContentCanAccessFileUrls, False)):
            s.setAttribute(attr, val)
        webrtc = getattr(WA, "WebRTCPublicInterfacesOnly", None)
        if webrtc is not None:
            s.setAttribute(webrtc, bool(self.app.settings.get("webrtc_ip_protect")))
        self.app.apply_page_settings(self.page)

    def _wire(self):
        v, p = self.view, self.page
        p.titleChanged.connect(self._on_title)
        p.urlChanged.connect(self._on_url)
        p.iconChanged.connect(self._on_icon)
        v.loadProgress.connect(self._on_progress)
        v.loadFinished.connect(self._on_finished)
        p.loadingChanged.connect(self.on_loading_changed)
        p.linkHovered.connect(self._on_hover)
        p.permissionRequested.connect(self.on_permission)
        p.newWindowRequested.connect(self.on_new_window)
        p.fullScreenRequested.connect(self.on_fullscreen)
        p.authenticationRequired.connect(self.on_auth)
        p.proxyAuthenticationRequired.connect(self.on_proxy_auth)
        p.renderProcessTerminated.connect(self.on_render_terminated)
        p.windowCloseRequested.connect(lambda: self.closeRequested.emit(self))
        p.recentlyAudibleChanged.connect(lambda _a: self.audioChanged.emit())
        p.audioMutedChanged.connect(lambda _a: self.audioChanged.emit())
        p.certificateError.connect(self.on_cert_error)
        p.zoomFactorChanged.connect(lambda _z: self.zoomChanged.emit())
        p.findTextFinished.connect(self.find.on_result)
        for name, slot in (("desktopMediaRequested", self.on_desktop_media), ("fileSystemAccessRequested", self.on_fs_access),
                           ("printRequested", self.print_page), ("registerProtocolHandlerRequested", lambda r: r.reject())):
            sig = getattr(p, name, None)
            if sig is not None:
                sig.connect(slot)

    # ---- page background (what shows before a page has painted) ---------------------------------------
    def bg_color(self, url=None):
        """Our own pages use the theme colour; web pages start white like Chrome (dark if forced dark mode is on)."""
        colors = self.app.pal(self.private)
        u = url if url is not None else self.page.url()
        internal = u.isEmpty() or u.scheme() in (SCHEME, "about")
        if internal or (colors["dark"] and self.app.settings.get("web_dark_mode")):
            return QColor(colors["bar"])
        return QColor("#ffffff")

    def refresh_background(self, url=None):
        from . import enhance
        if not enhance.ENABLED:
            return
        try:
            c = self.bg_color(url)
            if c.rgba() != getattr(self, "_bg_rgba", None):      # re-setting the same colour repaints the whole view for nothing
                self._bg_rgba = c.rgba()
                self.page.setBackgroundColor(c)
        except Exception:
            log.debug("background colour", exc_info=True)

    # ---- state helpers ----------------------------------------------------------------
    def real_url(self):
        """What the address bar should show (the failed URL while an error page is displayed)."""
        if self.lazy_url:
            return QUrl(self.lazy_url)
        u = self.page.url()
        if u.isEmpty() and self.page.requestedUrl().isValid():
            u = self.page.requestedUrl()                     # navigation started but not committed yet
        if u.scheme() == SCHEME and u.host() == "error":
            q = parse_qs(u.query())
            if q.get("u"):
                return QUrl(q["u"][0])
        return u

    def is_internal(self):
        return self.page.url().scheme() == SCHEME

    def title(self):
        if self.lazy_url:
            return self.lazy_title or QUrl(self.lazy_url).host() or "Tab"
        t = self.page.title()
        if t and not t.startswith(("null://", "http://", "https://")):
            return t
        u = self.real_url()
        if u.scheme() == SCHEME:
            return {"newtab": "New Tab"}.get(u.host(), u.host().title())
        return u.host() or t or "New Tab"

    def load(self, text_or_url):
        url = QUrl(text_or_url) if isinstance(text_or_url, str) else text_or_url
        if not url.isValid() or url.isEmpty():
            return
        self.cert_failed = False
        self.lazy_url = ""
        self.page.load(url)
        self.last_active = time.time()
        if self.discarded:
            self.activate()

    def reload(self, hard=False):
        u = self.real_url()
        if self.page.url().host() == "error" and self.page.url().scheme() == SCHEME and u.isValid():
            self.load(u)
        elif hard:
            self.page.triggerAction(QWebEnginePage.WebAction.ReloadAndBypassCache)
        else:
            self.page.triggerAction(QWebEnginePage.WebAction.Reload)

    def stop(self):
        self.page.triggerAction(QWebEnginePage.WebAction.Stop)

    def activate(self):
        self.last_active = time.time()
        if self.lazy_url:                              # restored tab becomes visible: load it now
            url, self.lazy_url = self.lazy_url, ""
            self.load(url)
            self.titleChanged.emit(self)
        if self.discarded:
            self.discarded = False
            self.page.setLifecycleState(QWebEnginePage.LifecycleState.Active)
            self.titleChanged.emit(self)

    def discard(self):
        try:
            if self.page.isVisible() or self.discarded or self.is_internal() or self.devtools is not None:
                return False
            self.page.setLifecycleState(QWebEnginePage.LifecycleState.Discarded)
            self.discarded = True
            self.titleChanged.emit(self)
            return True
        except Exception:
            return False

    # ---- navigation hooks ---------------------------------------------------------------
    def before_navigation(self, url):
        """Runs before every main-frame navigation: per-site settings and the JS API gate."""
        self.current_origin = origin_of(url.toString())
        self.app.apply_site_policy(self, url)
        self.refresh_background(url)
        self.view.pan_cursor.disarm()
        self.view.pan_cursor.attach()
        cosmetic = getattr(self.app.adblock, "cosmetic", None)
        if cosmetic is not None:
            cosmetic.prepare(self.page, url)

    def open_external(self, url):
        r = QMessageBox.question(self.window(), "Open external application?",
                                 f"This page wants to open a “{url.scheme()}” link in another application:\n\n{url.toString()[:200]}",
                                 QMessageBox.StandardButton.Open | QMessageBox.StandardButton.Cancel)
        if r == QMessageBox.StandardButton.Open:
            QDesktopServices.openUrl(url)


    # ---- page signal handlers -------------------------------------------------------------
    def _on_title(self, t):
        if not self.private and t and self.page.url().scheme() in ("http", "https"):
            self.app.db.update_title(self.page.url().toString(), t)
        self.titleChanged.emit(self)

    def _on_url(self, url):
        self.urlChanged.emit(self)
        self.securityChanged.emit()

    def _on_icon(self, ic):
        self.iconChanged.emit(self)
        if self.private or ic.isNull():
            return
        try:
            host = self.page.url().host()
            if host and self.page.url().scheme() in ("http", "https"):
                pm = ic.pixmap(32, 32)
                if not pm.isNull():
                    buf = QBuffer()
                    buf.open(QIODevice.OpenModeFlag.WriteOnly)
                    pm.toImage().save(buf, "PNG")
                    self.app.db.set_favicon(host, bytes(buf.data()))
        except Exception:
            log.debug("favicon store failed", exc_info=True)

    def _on_progress(self, p):
        self.progress = p
        self.progressChanged.emit(p)

    def _on_hover(self, link):
        if not link:
            self.hover.hide()
            return
        fm = self.hover.fontMetrics()
        self.hover.setText(fm.elidedText(link, Qt.TextElideMode.ElideMiddle, max(200, self.width() // 2)))
        self.hover.adjustSize()
        self._place_overlays()
        self.hover.show()
        self.hover.raise_()

    def on_loading_changed(self, info):
        try:
            st = info.status()
            if st == LS.LoadStartedStatus:
                self.loading = True
                self.loadingChanged.emit(True)
            elif st in (LS.LoadSucceededStatus, LS.LoadStoppedStatus):
                self.loading = False
                self.loadingChanged.emit(False)
            elif st == LS.LoadFailedStatus:
                self.loading = False
                self.loadingChanged.emit(False)
                self._load_failed(info)
        except Exception:
            crash.log.exception("loading changed")

    def _load_failed(self, info):
        code = info.errorCode()
        dom = info.errorDomain()
        name = (info.errorString() or "").replace("net::", "")
        url = info.url()
        if code == -3 or dom in (ED.InternalErrorDomain, ED.HttpStatusCodeDomain, ED.NoErrorDomain, ED.CertificateErrorDomain):
            return
        if url.scheme() == SCHEME:
            return
        if self.http_fallback and url.scheme() == "https" and not self._upgraded and "NAME_NOT_RESOLVED" not in name and "INTERNET_DISCONNECTED" not in name:
            self._upgraded = True
            fb, self.http_fallback = self.http_fallback, ""
            log.info("HTTPS-first fallback to %s", fb)
            QTimer.singleShot(0, lambda: self.load(fb))
            return
        self._show_error("net", name.split(" ")[0] or f"ERR_{code}", url.toString())

    def _show_error(self, kind, code, url, desc=""):
        u = f"{SCHEME}://error?kind={kind}&code={quote(code)}&u={quote(url, safe='')}" + (f"&desc={quote(desc)}" if desc else "")
        QTimer.singleShot(0, lambda: self.load(u))

    def on_cert_error(self, err):
        try:
            host = err.url().host()
            if host in self.app.cert_allow and err.isOverridable():
                err.acceptCertificate()
                return
            err.rejectCertificate()
            self.cert_failed = True
            self._show_error("cert", "ERR_CERT", err.url().toString(), err.description())
        except Exception:
            crash.log.exception("cert error")
            err.rejectCertificate()

    def _on_finished(self, ok):
        try:
            self.progress = 100
            url = self.page.url()
            if url.scheme() in ("http", "https", "file"):
                self.app.apply_zoom(self)
            if ok and not self.private and url.scheme() in ("http", "https") and url.toString() != self._last_history_url:
                self._last_history_url = url.toString()
                typed = bool(self.typed_url) and url.toString().rstrip("/").startswith(self.typed_url.rstrip("/"))
                self.typed_url = ""
                self.app.db.add_visit(url.toString(), self.page.title(), typed)
            if ok and url.scheme() in ("http", "https") and getattr(self.app.adblock, "cosmetic", None) is not None:
                self.app.adblock.cosmetic.after_load(self.page)
            if ok and url.host() == "newtab" and url.scheme() == SCHEME:
                self.focusOmnibox.emit()
            self.securityChanged.emit()
        except Exception:
            crash.log.exception("load finished")

    def on_render_terminated(self, status, code):
        try:
            if status == QWebEnginePage.RenderProcessTerminationStatus.NormalTerminationStatus:
                return
            log.error("Renderer terminated (%s, exit %s) for %s", status, code, self.page.url().toString())
            self._show_error("crash", "CRASHED", self.real_url().toString())
        except Exception:
            crash.log.exception("render terminated")


    # ---- windows / popups / fullscreen / auth ----------------------------------------------------
    def on_new_window(self, req):
        try:
            D = req.DestinationType
            dest = req.destination()
            if req.requestedUrl().scheme() == SCHEME and not self.is_internal():
                return                                          # web content may never open internal pages
            origin = origin_of(self.page.url().toString())
            if not req.isUserInitiated() and self.app.perms.effective(origin, "popups", self.private) == "block":
                self.blocked_popups += 1
                self.popupBlocked.emit()
                log.info("Blocked pop-up from %s: %s", origin, req.requestedUrl().toString())
                return
            if dest == D.InNewWindow:
                self.openWindow.emit(req.requestedUrl().toString(), self.private)
                return
            self.openTab.emit(req.requestedUrl().toString(), dest == D.InNewBackgroundTab, req)
        except Exception:
            crash.log.exception("new window")

    def on_fullscreen(self, req):
        req.accept()
        self.fullscreenToggled.emit(req.toggleOn())


    def session_entry(self):
        return {"url": self.real_url().toString(), "title": self.title(), "pinned": self.pinned}

    def cleanup(self):
        self.close_devtools()
        cosmetic = getattr(self.app.adblock, "cosmetic", None)
        if cosmetic is not None:
            cosmetic.forget(self.page)
        try:
            self.page.setAudioMuted(True)
            self.view.setPage(None)
            self.page.deleteLater()
        except Exception:
            pass

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._place_overlays()

    def _place_overlays(self):
        self.find.move(max(0, self.width() - self.find.width() - 18), 8)
        self.bubble.move(12, 8)
        self.hover.move(0, self.height() - self.hover.height())


