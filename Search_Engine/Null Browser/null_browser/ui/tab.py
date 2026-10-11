"""A browser tab: page + view + overlays (find bar, permission prompts, hover status, DevTools)."""
import logging
import os
import re
import time
from urllib.parse import parse_qs, quote, urlsplit

from PyQt6.QtCore import QBuffer, QIODevice, QSize, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QDesktopServices
from PyQt6.QtWebEngineCore import QWebEngineLoadingInfo, QWebEnginePage, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout, QInputDialog, QLabel,
                             QLineEdit, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QToolButton,
                             QVBoxLayout, QWidget)

from ..constants import SCHEME
from ..core import crash
from ..core.permissions import ASK_PREFIX, BY_ID, PROMPT_VERBS, QT_PERMISSION_MAP, origin_of
from . import icons

log = logging.getLogger("null.tab")
WA = QWebEngineSettings.WebAttribute
NAV = QWebEnginePage.NavigationType
LS = QWebEngineLoadingInfo.LoadStatus
ED = QWebEngineLoadingInfo.ErrorDomain
EXTERNAL_OK = {"http", "https", "file", SCHEME, "view-source", "data", "blob", "about", "ftp", "javascript", "qrc",
               "filesystem", "devtools", "chrome-devtools"}
ZOOMS = [0.25, 0.33, 0.5, 0.67, 0.75, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 4.0, 5.0]


class BrowserPage(QWebEnginePage):
    def __init__(self, profile, tab):
        super().__init__(profile, tab)
        self.tab = tab
        self.console = []

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        try:
            scheme = url.scheme().lower()
            if scheme == SCHEME and self.url().scheme() != SCHEME:
                # Only the user (typed / load() / history / reload) may open internal pages - never web content.
                if nav_type not in (NAV.NavigationTypeTyped, NAV.NavigationTypeReload, NAV.NavigationTypeBackForward):
                    log.warning("Blocked web page navigation to %s", url.toString())
                    return False
            if is_main_frame:
                if scheme not in EXTERNAL_OK:
                    self.tab.open_external(url)
                    return False
                self.tab.before_navigation(url)
            return True
        except Exception:
            log.exception("acceptNavigationRequest")
            return True

    def javaScriptConsoleMessage(self, level, message, line, source):
        self.console.append((time.time(), getattr(level, "value", 0), message, line, source))
        del self.console[:-300]

    def javaScriptConfirm(self, origin, msg):
        if msg.startswith(ASK_PREFIX):                       # our API shim asking for a permission
            return self.tab.ask_shim_permission(msg[len(ASK_PREFIX):], origin)
        return QMessageBox.question(self.tab.window(), origin.host() or "Message from page", msg) == QMessageBox.StandardButton.Yes

    def javaScriptAlert(self, origin, msg):
        QMessageBox.information(self.tab.window(), origin.host() or "Message from page", msg)

    def javaScriptPrompt(self, origin, msg, default):
        text, ok = QInputDialog.getText(self.tab.window(), origin.host() or "Message from page", msg, text=default)
        return ok, text


class WebView(QWebEngineView):
    def __init__(self, tab):
        super().__init__(tab)
        self.tab = tab

    def contextMenuEvent(self, ev):
        try:
            self.tab.show_context_menu(self.mapToGlobal(ev.pos()))
            ev.accept()
        except Exception:
            crash.log.exception("context menu")


class _DevToolsView(QWebEngineView):
    closeRequested = pyqtSignal()

    def closeEvent(self, ev):
        self.closeRequested.emit()
        super().closeEvent(ev)


class Tab(QWidget):
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

    # ---- setup ----------------------------------------------------------------------
    def _configure_settings(self):
        s = self.page.settings()
        for attr, val in ((WA.ErrorPageEnabled, False), (WA.FullScreenSupportEnabled, True), (WA.JavascriptCanOpenWindows, True),
                          (WA.PluginsEnabled, True), (WA.PdfViewerEnabled, True), (WA.ScreenCaptureEnabled, True),
                          (WA.WebGLEnabled, True), (WA.LocalStorageEnabled, True), (WA.FocusOnNavigationEnabled, True),
                          (WA.AllowWindowActivationFromJavaScript, False), (WA.HyperlinkAuditingEnabled, False),
                          (WA.LocalContentCanAccessRemoteUrls, False), (WA.LocalContentCanAccessFileUrls, False)):
            s.setAttribute(attr, val)
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

    def open_external(self, url):
        r = QMessageBox.question(self.window(), "Open external application?",
                                 f"This page wants to open a “{url.scheme()}” link in another application:\n\n{url.toString()[:200]}",
                                 QMessageBox.StandardButton.Open | QMessageBox.StandardButton.Cancel)
        if r == QMessageBox.StandardButton.Open:
            QDesktopServices.openUrl(url)

    def ask_shim_permission(self, feature, origin_url):
        """Synchronous permission prompt used by the JS API gate (called from javaScriptConfirm)."""
        if feature not in BY_ID:
            return False
        origin = origin_of(self.page.url().toString()) or origin_of(origin_url.toString())
        val = self.app.perms.effective(origin, feature, self.private)
        if val == "allow":
            return True
        if val == "block":
            return False
        box = QMessageBox(self.window())
        box.setWindowTitle("Permission request")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(f"{origin or 'This site'} wants to {PROMPT_VERBS.get(feature, 'use ' + BY_ID[feature]['label'])}")
        allow = box.addButton("Allow", QMessageBox.ButtonRole.AcceptRole)
        once = box.addButton("Allow this time", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Block", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        c = box.clickedButton()
        if c is allow:
            self.app.perms.set_site(origin, feature, "allow", self.private)
            return True
        if c is once:
            return True
        self.app.perms.set_site(origin, feature, "block", self.private)
        return False

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

    # ---- permissions ------------------------------------------------------------------------
    def on_permission(self, perm):
        try:
            feats = QT_PERMISSION_MAP.get(perm.permissionType().name)
            if not feats:
                perm.deny()
                return
            origin = origin_of(perm.origin().toString()) or self.current_origin
            vals = [self.app.perms.effective(origin, f, self.private) for f in feats]
            if "block" in vals:
                perm.deny()
            elif all(v == "allow" for v in vals):
                perm.grant()
            else:
                self.bubble.request(origin, [f for f, v in zip(feats, vals) if v != "allow"], feats, perm)
        except Exception:
            crash.log.exception("permission request")
            try:
                perm.deny()
            except Exception:
                pass

    def on_fs_access(self, req):
        origin = origin_of(req.origin().toString()) or self.current_origin
        v = self.app.perms.effective(origin, "file_editing", self.private)
        if v == "block":
            return req.reject()
        if v == "ask":
            r = QMessageBox.question(self.window(), "Edit files?", f"{origin} wants to access files or folders on your device.")
            if r != QMessageBox.StandardButton.Yes:
                return req.reject()
        req.accept()

    def on_desktop_media(self, req):
        origin = origin_of(self.page.url().toString())
        if self.app.perms.effective(origin, "screen_capture", self.private) == "block":
            return req.cancel()
        try:
            model = req.screensModel()
            names = [str(model.data(model.index(i, 0))) for i in range(model.rowCount())]
            if not names:
                return req.cancel()
            pick = names[0]
            if len(names) > 1:
                pick, ok = QInputDialog.getItem(self.window(), "Share your screen", f"Choose what {origin} can see:", names, 0, False)
                if not ok:
                    return req.cancel()
            req.selectScreen(model.index(names.index(pick), 0))
        except Exception:
            crash.log.exception("desktop media")
            req.cancel()

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

    def on_auth(self, url, auth):
        self._auth_dialog(f"Sign in to {url.host()}", auth.realm() or url.host(), auth)

    def on_proxy_auth(self, url, auth, host):
        self._auth_dialog(f"Proxy {host}", auth.realm() or host, auth)

    def _auth_dialog(self, title, realm, auth):
        d = QDialog(self.window())
        d.setWindowTitle(title)
        form = QFormLayout(d)
        form.addRow(QLabel(f"<b>{title}</b><br>Realm: {realm}"))
        user, pw = QLineEdit(), QLineEdit()
        pw.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Username", user)
        form.addRow("Password", pw)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        form.addRow(bb)
        if d.exec():
            auth.setUser(user.text())
            auth.setPassword(pw.text())
        else:
            auth.setUser("")
            auth.setPassword("")

    # ---- zoom -------------------------------------------------------------------------------------
    def zoom_step(self, direction):
        cur = self.page.zoomFactor()
        idx = min(range(len(ZOOMS)), key=lambda i: abs(ZOOMS[i] - cur))
        self.set_zoom(ZOOMS[max(0, min(len(ZOOMS) - 1, idx + direction))])

    def set_zoom(self, z):
        self.page.setZoomFactor(z)
        host = self.page.url().host()
        if host and not self.private and self.page.url().scheme() in ("http", "https"):
            self.app.db.set_zoom(host, z)
        self.zoomChanged.emit()

    # ---- context menu -----------------------------------------------------------------------------
    def show_context_menu(self, global_pos):
        d = self.view.lastContextMenuRequest()
        if d is None:
            return
        WAct = QWebEnginePage.WebAction
        T = d.MediaType
        m = QMenu(self)
        act = lambda text, fn, ic=None, enabled=True: self._add(m, text, fn, ic, enabled)
        link, media, sel = d.linkUrl(), d.mediaUrl(), d.selectedText()
        if link.isValid():
            act("Open link in new tab", lambda: self.openTab.emit(link.toString(), False, None), "plus")
            act("Open link in new window", lambda: self.openWindow.emit(link.toString(), False), "external")
            act("Open link in InPrivate window", lambda: self.openWindow.emit(link.toString(), True), "eye_off")
            m.addSeparator()
            act("Save link as…", lambda: self.page.triggerAction(WAct.DownloadLinkToDisk), "download")
            act("Copy link address", lambda: self.page.triggerAction(WAct.CopyLinkToClipboard), "copy")
            m.addSeparator()
        if media.isValid() and d.mediaType() == T.MediaTypeImage:
            act("Open image in new tab", lambda: self.openTab.emit(media.toString(), False, None), "plus")
            act("Save image as…", lambda: self.page.triggerAction(WAct.DownloadImageToDisk), "download")
            act("Copy image", lambda: self.page.triggerAction(WAct.CopyImageToClipboard), "copy")
            act("Copy image address", lambda: self.page.triggerAction(WAct.CopyImageUrlToClipboard))
            m.addSeparator()
        elif media.isValid() and d.mediaType() in (T.MediaTypeVideo, T.MediaTypeAudio):
            act("Save media as…", lambda: self.page.triggerAction(WAct.DownloadMediaToDisk), "download")
            act("Copy media address", lambda: self.page.triggerAction(WAct.CopyMediaUrlToClipboard))
            m.addSeparator()
        if d.isContentEditable():
            f, E = d.editFlags(), d.EditFlag
            act("Undo", lambda: self.page.triggerAction(WAct.Undo), enabled=bool(f & E.CanUndo))
            act("Redo", lambda: self.page.triggerAction(WAct.Redo), enabled=bool(f & E.CanRedo))
            m.addSeparator()
            act("Cut", lambda: self.page.triggerAction(WAct.Cut), enabled=bool(f & E.CanCut))
            act("Copy", lambda: self.page.triggerAction(WAct.Copy), "copy", bool(f & E.CanCopy))
            act("Paste", lambda: self.page.triggerAction(WAct.Paste), enabled=bool(f & E.CanPaste))
            act("Select all", lambda: self.page.triggerAction(WAct.SelectAll), enabled=bool(f & E.CanSelectAll))
            m.addSeparator()
        elif sel:
            act("Copy", lambda: self.page.triggerAction(WAct.Copy), "copy")
            short = sel.strip()[:30] + ("…" if len(sel.strip()) > 30 else "")
            act(f"Search {self.app.search.current()['name']} for “{short}”",
                lambda: self.openTab.emit(self.app.search.search_url(sel.strip()), False, None), "search")
            m.addSeparator()
        if not link.isValid() and not d.isContentEditable() and not sel:
            h = self.page.history()
            act("Back", lambda: self.page.triggerAction(WAct.Back), "back", h.canGoBack())
            act("Forward", lambda: self.page.triggerAction(WAct.Forward), "forward", h.canGoForward())
            act("Reload", self.reload, "reload")
            m.addSeparator()
            act("Save as…", self.save_page, "download")
            act("Print…", self.print_page, "print")
            act("Find in page", self.show_find, "search")
            m.addSeparator()
        act("View page source", self.view_source, "code")
        act("Inspect", lambda: self.toggle_devtools(inspect=True), "tool")
        m.exec(global_pos)
        m.deleteLater()

    def _add(self, menu, text, fn, icon_name=None, enabled=True):
        a = QAction(text, menu)
        if icon_name:
            a.setIcon(self.app.icon(icon_name, private=self.private))
        a.setEnabled(enabled)
        a.triggered.connect(lambda *_: crash.guarded(fn)())
        menu.addAction(a)
        return a

    # ---- tools --------------------------------------------------------------------------------------
    def view_source(self):
        url = self.real_url()
        if url.scheme() in ("http", "https", "file"):
            source_url = url.toString()
            try:
                self.page.toHtml(lambda source: self._show_source(source or "", source_url))
            except Exception:
                crash.log.exception("could not read page source")

    @crash.guarded(quiet=True)
    def _show_source(self, source, source_url):
        dialog = QDialog(self.window())
        dialog.setWindowTitle(f"Page source: {QUrl(source_url).host() or source_url}")
        dialog.resize(1000, 700)
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit(dialog)
        text.setReadOnly(True)
        text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        text.setPlainText(source or "(empty document)")
        layout.addWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=dialog)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def _default_name(self):
        return re.sub(r"[^\w\- .]", "_", self.title())[:80] or "page"

    def save_page(self):
        from PyQt6.QtWidgets import QFileDialog
        path, flt = QFileDialog.getSaveFileName(self.window(), "Save page as", os.path.join(self.app.downloads.target_dir(), self._default_name()),
                                                "Web page, complete (*.html);;Web page, HTML only (*.html);;Web archive MHTML (*.mhtml)")
        if not path:
            return
        fmt = QWebEnginePage.SavePageFormat
        self.page.save(path, fmt.CompleteHtmlSaveFormat if "complete" in flt else fmt.SingleHtmlSaveFormat if "only" in flt else fmt.MimeHtmlSaveFormat)

    def save_pdf(self):
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self.window(), "Save as PDF", os.path.join(self.app.downloads.target_dir(), self._default_name() + ".pdf"), "PDF (*.pdf)")
        if path:
            self.page.printToPdf(path)
            self.app.notifier.notify("PDF saved", os.path.basename(path), on_click=lambda: self.app.downloads.show_in_folder(path))

    def print_page(self, *_):
        try:
            from PyQt6.QtPrintSupport import QPrintDialog, QPrinter
            printer = QPrinter()
            if QPrintDialog(printer, self.window()).exec():
                self.page.print(printer, lambda ok: None if ok else self.app.notifier.notify("Print failed", self.title(), force=True))
        except Exception:
            crash.log.exception("print")
            self.save_pdf()

    def show_find(self):
        self.find.open()

    def toggle_devtools(self, inspect=False):
        if self.devtools is not None and not inspect:
            return self.close_devtools()
        if self.devtools is None:
            self.open_devtools()
        if inspect:
            QTimer.singleShot(600, lambda: self.page.triggerAction(QWebEnginePage.WebAction.InspectElement))

    def open_devtools(self):
        dock = self.app.settings.get("devtools_dock")
        view = _DevToolsView()
        dev_page = QWebEnginePage(self.profile, view)
        view.setPage(dev_page)
        self.page.setDevToolsPage(dev_page)
        self.devtools = view
        dev_page.loadFinished.connect(lambda _ok: self._restyle_devtools())
        view.closeRequested.connect(lambda: QTimer.singleShot(0, self.close_devtools))
        if dock == "window":
            view.setWindowTitle(f"DevTools - {self.title()}")
            view.setWindowIcon(icons.app_icon())
            view.resize(1100, 760)
            view.show()
        else:
            host = QWidget(self)
            host.setObjectName("devtoolsHost")
            layout = QVBoxLayout(host)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            header = QFrame(host)
            header.setObjectName("devtoolsHeader")
            header_layout = QHBoxLayout(header)
            header_layout.setContentsMargins(12, 2, 6, 2)
            label = QLabel("Developer tools", header)
            close = QToolButton(header)
            close.setObjectName("devtoolsClose")
            close.setText("\u2715")
            close.setToolTip("Close developer tools")
            close.clicked.connect(self.close_devtools)
            header_layout.addWidget(label)
            header_layout.addStretch(1)
            header_layout.addWidget(close)
            layout.addWidget(header)
            layout.addWidget(view, 1)
            self.devtools_host = host
            self._restyle_devtools()
            self.split.setOrientation(Qt.Orientation.Vertical if dock == "bottom" else Qt.Orientation.Horizontal)
            self.split.addWidget(host)
            total = self.split.height() if dock == "bottom" else self.split.width()
            self.split.setSizes([int(total * 0.55), int(total * 0.45)])

    def _restyle_devtools(self):
        if self.devtools is None:
            return
        colors = self.app.pal(self.private)
        self.devtools.page().setBackgroundColor(QColor(colors["bar"]))
        self.devtools.page().settings().setAttribute(WA.ForceDarkMode, colors["dark"])
        mode = "dark" if colors["dark"] else "default"
        script = (
            "(() => {"
            f"document.documentElement.classList.toggle('theme-with-dark-background', {str(colors['dark']).lower()});"
            f"try {{ localStorage.setItem('uiTheme', '{mode}'); }} catch (e) {{}}"
            "})()"
        )
        self.devtools.page().runJavaScript(script)
        host = self.devtools_host
        if host is not None:
            header = host.findChild(QFrame, "devtoolsHeader")
            if header is not None:
                header.setStyleSheet(f"background:{colors['bar']};border-bottom:1px solid {colors['border']};")

    def close_devtools(self):
        if self.devtools is None:
            return
        try:
            self.page.setDevToolsPage(None)
        except Exception:
            log.exception("could not detach DevTools page")
        view, self.devtools = self.devtools, None
        host, self.devtools_host = self.devtools_host, None
        view.hide()
        if host is not None:
            host.setParent(None)
            host.deleteLater()
        else:
            view.setParent(None)
            view.deleteLater()

    def session_entry(self):
        return {"url": self.real_url().toString(), "title": self.title(), "pinned": self.pinned}

    def cleanup(self):
        self.close_devtools()
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


class FindBar(QFrame):
    def __init__(self, tab):
        super().__init__(tab)
        self.tab = tab
        self.setObjectName("findbar")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 6, 6)
        lay.setSpacing(4)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Find in page")
        self.edit.setFixedWidth(220)
        self.count = QLabel("")
        self.count.setMinimumWidth(52)
        self.prev, self.next, self.close_btn = QToolButton(), QToolButton(), QToolButton()
        for b, name, tip in ((self.prev, "up", "Previous (Shift+Enter)"), (self.next, "down", "Next (Enter)"), (self.close_btn, "close", "Close (Esc)")):
            b.setToolTip(tip)
            b.setProperty("iconname", name)
        for w in (self.edit, self.count, self.prev, self.next, self.close_btn):
            lay.addWidget(w)
        self.edit.textChanged.connect(self.search)
        self.edit.returnPressed.connect(lambda: self.search(self.edit.text(), True))
        self.next.clicked.connect(lambda: self.search(self.edit.text(), True))
        self.prev.clicked.connect(lambda: self.search(self.edit.text(), False))
        self.close_btn.clicked.connect(self.close_bar)
        self.edit.installEventFilter(self)
        self.restyle()
        self.adjustSize()

    def restyle(self):
        for b in (self.prev, self.next, self.close_btn):
            b.setIcon(self.tab.app.icon(b.property("iconname"), private=self.tab.private))
            b.setIconSize(QSize(16, 16))

    def open(self):
        self.restyle()
        self.show()
        self.raise_()
        self.adjustSize()
        self.tab._place_overlays()
        sel = self.tab.page.selectedText()
        if sel:
            self.edit.setText(sel.splitlines()[0][:100])
        self.edit.setFocus()
        self.edit.selectAll()
        if self.edit.text():
            self.search(self.edit.text())

    def close_bar(self):
        self.hide()
        self.tab.page.findText("")
        self.tab.view.setFocus()

    def search(self, text, forward=True):
        self.tab.page.findText(text, QWebEnginePage.FindFlag(0) if forward else QWebEnginePage.FindFlag.FindBackward)
        if not text:
            self.count.setText("")

    def on_result(self, res):
        if not self.edit.text():
            return
        n = res.numberOfMatches()
        self.count.setText(f"{res.activeMatchOrdinal()}/{n}" if n else "0/0")
        self.edit.setStyleSheet("" if n else "QLineEdit { color: #d93a4a; }")

    def eventFilter(self, obj, ev):
        if obj is self.edit and ev.type() == ev.Type.KeyPress:
            if ev.key() == Qt.Key.Key_Escape:
                self.close_bar()
                return True
            if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and ev.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.search(self.edit.text(), False)
                return True
        return super().eventFilter(obj, ev)


class PermissionBubble(QFrame):
    """Chrome-style permission prompt anchored to the top-left of the page."""

    def __init__(self, tab):
        super().__init__(tab)
        self.tab = tab
        self.setObjectName("bubble")
        self.queue, self.current = [], None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)
        self.title = QLabel()
        self.title.setWordWrap(True)
        self.title.setStyleSheet("font-size: 14px; font-weight: 600;")
        self.sub = QLabel()
        self.sub.setWordWrap(True)
        self.sub.setStyleSheet("color: gray; font-size: 12px;")
        self.btn_allow = QPushButton("Allow while visiting the site")
        self.btn_once = QPushButton("Allow this time")
        self.btn_deny = QPushButton("Don't allow")
        self.btn_allow.setObjectName("primary")
        for w in (self.title, self.sub, self.btn_allow, self.btn_once, self.btn_deny):
            lay.addWidget(w)
        self.setFixedWidth(330)
        self.btn_allow.clicked.connect(lambda: self.decide("allow"))
        self.btn_once.clicked.connect(lambda: self.decide("once"))
        self.btn_deny.clicked.connect(lambda: self.decide("block"))

    def request(self, origin, ask_feats, all_feats, perm):
        self.queue.append((origin, ask_feats, all_feats, perm))
        if self.current is None:
            self._next()

    def _next(self):
        if not self.queue:
            self.current = None
            self.hide()
            return
        self.current = self.queue.pop(0)
        origin, _ask, allf, _perm = self.current
        verbs = " and ".join(PROMPT_VERBS.get(f, "use " + BY_ID[f]["label"].lower()) for f in allf)
        self.title.setText(f"{urlsplit(origin).hostname or origin} wants to {verbs}")
        self.sub.setText("In a private window the decision is forgotten when all private windows close." if self.tab.private
                         else "Your decision is remembered for this site. Change it any time from the icon left of the address.")
        self.adjustSize()
        self.show()
        self.raise_()
        self.tab._place_overlays()

    def decide(self, choice):
        if self.current is None:
            return
        origin, _ask, allf, perm = self.current
        try:
            if choice == "block":
                for f in allf:
                    self.tab.app.perms.set_site(origin, f, "block", self.tab.private)
                perm.deny()
            else:
                if choice == "allow":
                    for f in allf:
                        self.tab.app.perms.set_site(origin, f, "allow", self.tab.private)
                perm.grant()
        except Exception:
            crash.log.exception("permission decision")
        self.tab.securityChanged.emit()
        self._next()
