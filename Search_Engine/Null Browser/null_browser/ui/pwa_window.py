"""Window of an installed web app: the page, a slim bar (back / reload / title / menu) and nothing else."""
import logging
import time

from PyQt6.QtCore import QSize, Qt, QTimer, QUrl
from PyQt6.QtGui import QAction, QColor, QIcon, QKeySequence, QPixmap
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox, QProgressBar, QToolButton, QVBoxLayout, QWidget

from ..core import crash, pwa
from .tab import Tab

log = logging.getLogger("null.pwa")


class PwaWindow(QMainWindow):
    def __init__(self, app, rec, url=None):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.app, self.aid = app, rec["id"]
        self.private = False
        self.profile = app.pwa_profile(self.aid)
        self.setMinimumSize(420, 320)
        self.resize(1100, 760)

        root = QWidget()
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.bar = QWidget()
        self.bar.setObjectName("pwabar")
        h = QHBoxLayout(self.bar)
        h.setContentsMargins(6, 3, 6, 3)
        h.setSpacing(2)
        self.back_btn = self._btn("back", "Back", lambda: self.tab.page.triggerAction(self.tab.page.WebAction.Back))
        self.fwd_btn = self._btn("forward", "Forward", lambda: self.tab.page.triggerAction(self.tab.page.WebAction.Forward))
        self.reload_btn = self._btn("reload", "Reload", self._reload_or_stop)
        self.icon_lbl = QLabel()
        self.icon_lbl.setFixedSize(20, 20)
        self.icon_lbl.setScaledContents(True)
        self.title_lbl = QLabel()
        self.scope_lbl = QLabel()                       # shown while the app is on a page outside its scope (sign-in pages, external links)
        self.scope_lbl.hide()
        self.menu_btn = self._btn("more", "Menu", self._menu)
        for w in (self.back_btn, self.fwd_btn, self.reload_btn):
            h.addWidget(w)
        h.addSpacing(6)
        h.addWidget(self.icon_lbl)
        h.addSpacing(4)
        h.addWidget(self.title_lbl)
        h.addWidget(self.scope_lbl)
        h.addStretch(1)
        h.addWidget(self.menu_btn)
        v.addWidget(self.bar)
        self.load = QProgressBar()
        self.load.setTextVisible(False)
        self.load.setFixedHeight(3)
        self.load.setRange(0, 100)
        v.addWidget(self.load)

        self.tab = Tab(app, self.profile, False)
        self.tab.nav_guard = self._nav_guard
        v.addWidget(self.tab, 1)
        t = self.tab
        t.titleChanged.connect(lambda *_: self._title())
        t.urlChanged.connect(lambda *_: self._url())
        t.loadingChanged.connect(self._loading)
        t.progressChanged.connect(lambda p: self.load.setValue(p if p < 100 else 0))
        t.openTab.connect(lambda url_, bg, req: app.open_urls([url_]) if req is None else self._popup(req))
        t.openWindow.connect(lambda u, p: app.open_urls([u], p))
        t.closeRequested.connect(lambda *_: self.close())
        t.fullscreenToggled.connect(self._fullscreen)
        t.view.loadFinished.connect(self._loaded_once)
        self._checked = False
        for seq, fn in (("Ctrl+R|F5", self.tab.reload), ("Ctrl+Shift+R|Ctrl+F5", lambda: self.tab.reload(hard=True)), ("Alt+Left", lambda: self.back_btn.click()),
                        ("Alt+Right", lambda: self.fwd_btn.click()), ("Ctrl+F", self.tab.show_find), ("Ctrl++|Ctrl+=", lambda: self.tab.zoom_step(1)),
                        ("Ctrl+-", lambda: self.tab.zoom_step(-1)), ("Ctrl+0", lambda: self.tab.set_zoom(1.0)), ("F11", lambda: self._fullscreen(not self.isFullScreen())),
                        ("F12|Ctrl+Shift+I", self.tab.toggle_devtools), ("Ctrl+P", self.tab.print_page), ("Ctrl+W|Alt+F4", self.close)):
            a = QAction(self)
            a.setShortcuts([QKeySequence(s) for s in seq.split("|")])
            a.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            a.triggered.connect(lambda *_a, f=fn: crash.guarded(f)())
            self.addAction(a)
        app.themeChanged.connect(self.restyle)
        self.refresh_identity()
        self.tab.load(url or rec["start_url"])

    # ---- look ----------------------------------------------------------------------------------
    def rec(self):
        return self.app.pwa.get(self.aid) or {}

    def refresh_identity(self):
        rec = self.rec()
        self.setWindowTitle(rec.get("name", "App"))
        pm = QPixmap(self.app.pwa.icon_path(self.aid))
        if not pm.isNull():
            self.setWindowIcon(QIcon(pm))
            self.icon_lbl.setPixmap(pm)
        self.restyle()
        self._title()

    def restyle(self):
        pal = self.app.pal(False)
        theme = self.rec().get("theme_color") or ""
        bg = theme if QColor(theme).isValid() and theme else pal["bar"]
        fg = pwa_contrast(bg) if theme else pal["text"]
        self._fg = fg
        self.bar.setStyleSheet(f"QWidget#pwabar{{background:{bg};}} QLabel{{color:{fg};background:transparent;font-weight:600;}} "
                               f"QToolButton{{background:transparent;border-radius:14px;padding:4px;}} QToolButton:hover{{background:rgba(128,128,128,.28);}}")
        self.load.setStyleSheet(f"QProgressBar{{background:transparent;border:none;}} QProgressBar::chunk{{background:{self.app.accent};}}")
        for b, name in ((self.back_btn, "back"), (self.fwd_btn, "forward"), (self.reload_btn, "reload"), (self.menu_btn, "more")):
            b.setIcon(self.app.icon(name, color=fg, size=18))

    def _btn(self, icon, tip, fn):
        b = QToolButton()
        b.setToolTip(tip)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.setIconSize(QSize(18, 18))
        b.setFixedSize(30, 28)
        b.clicked.connect(lambda *_: crash.guarded(fn)())
        return b

    def _title(self):
        self.title_lbl.setText(self.rec().get("name") or self.tab.title())

    def _url(self):
        u = self.tab.page.url()
        h = self.tab.page.history()
        self.back_btn.setEnabled(h.canGoBack())
        self.fwd_btn.setEnabled(h.canGoForward())
        inside = u.scheme() not in ("http", "https") or pwa.in_scope(u.toString(), self.rec().get("scope", u.toString()))
        self.scope_lbl.setVisible(not inside)
        if not inside:
            self.scope_lbl.setText("  •  " + u.host())

    def _loading(self, on):
        self.reload_btn.setIcon(self.app.icon("stop" if on else "reload", color=self._fg, size=18))
        self._url()

    def _reload_or_stop(self):
        self.tab.stop() if self.tab.loading else self.tab.reload()

    def _fullscreen(self, on):
        self.bar.setVisible(not on)
        self.showFullScreen() if on else self.showNormal()

    # ---- navigation ----------------------------------------------------------------------------
    def _nav_guard(self, url, nav_type):
        """Clicking a link that leaves the app opens it in the browser; redirects and form posts (sign-in flows) stay here."""
        from PyQt6.QtWebEngineCore import QWebEnginePage
        if nav_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked and url.scheme() in ("http", "https"):
            if not pwa.in_scope(url.toString(), self.rec().get("scope", url.toString())) and url.host() != QUrl(self.rec().get("start_url", "")).host():
                self.app.open_urls([url.toString()])
                return False
        return True

    def _popup(self, req):
        """window.open() from the app (OAuth sign-in pop-ups, payment pages): a small window on the app's own profile, so the
        pop-up can talk back to the app (window.opener / postMessage) exactly as in Chrome."""
        win = QMainWindow(self)
        win.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        win.setWindowFlag(Qt.WindowType.Dialog, True)
        win.resize(520, 700)
        tab = Tab(self.app, self.profile, False)
        win.setCentralWidget(tab)
        tab.titleChanged.connect(lambda *_: win.setWindowTitle(tab.title()))
        tab.closeRequested.connect(lambda *_: win.close())
        tab.openTab.connect(lambda u, bg, r: self.app.open_urls([u]) if r is None else None)
        win.closeEvent = lambda ev, t=tab: (t.cleanup(), QMainWindow.closeEvent(win, ev))
        req.openIn(tab.page)
        win.show()

    # ---- updates -------------------------------------------------------------------------------
    def _loaded_once(self, ok):
        if self._checked or not ok:
            return
        self._checked = True
        rec = self.rec()
        hours = max(1, int(self.app.settings.get("pwa_update_hours") or 12))
        if rec.get("auto_update") and time.time() - rec.get("checked", 0) > hours * 3600:
            QTimer.singleShot(2500, lambda: self.app.pwa_check_update(self.aid, self.tab.page, force=False))

    def check_updates(self):
        self.app.pwa_check_update(self.aid, self.tab.page, force=True, callback=self.toast)

    def toast(self, text):
        old = getattr(self, "_toast", None)
        if old is not None:
            old.deleteLater()
        lab = QLabel(text, self.centralWidget())
        lab.setStyleSheet("background:#22232d;color:#fff;border-radius:10px;padding:9px 14px;")
        lab.adjustSize()
        lab.move((self.width() - lab.width()) // 2, self.height() - lab.height() - 28)
        lab.show()
        self._toast = lab
        QTimer.singleShot(4500, lambda l=lab: l.deleteLater())

    show_toast = toast

    # ---- menu ----------------------------------------------------------------------------------
    def _menu(self):
        m = QMenu(self)
        add = lambda text, fn: m.addAction(text, lambda: crash.guarded(fn)())
        add("Check for updates", self.check_updates)
        add("Reload (bypass cache)", lambda: self.tab.reload(hard=True))
        m.addSeparator()
        add("Find in page…", self.tab.show_find)
        add("Zoom in", lambda: self.tab.zoom_step(1))
        add("Zoom out", lambda: self.tab.zoom_step(-1))
        add("Print…", self.tab.print_page)
        add("Developer tools", self.tab.toggle_devtools)
        m.addSeparator()
        add("Open this page in Null Browser", lambda: self.app.open_urls([self.tab.real_url().toString()]))
        add("Create shortcut…", lambda: (self.app.create_shortcuts(self.aid), self.toast("Shortcuts created.")))
        add("App settings", lambda: self.app.open_urls(["null://settings/apps"]))
        m.addSeparator()
        add("Uninstall…", self._uninstall)
        m.exec(self.menu_btn.mapToGlobal(self.menu_btn.rect().bottomRight()) - self._menu_offset(m))
        m.deleteLater()

    def _menu_offset(self, m):
        from PyQt6.QtCore import QPoint
        return QPoint(m.sizeHint().width(), 0)

    def _uninstall(self):
        name = self.rec().get("name", "this app")
        r = QMessageBox.question(self, "Uninstall app", f"Uninstall “{name}” and delete its data (sign-ins, offline files)?",
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        if r == QMessageBox.StandardButton.Yes:
            QTimer.singleShot(0, lambda: self.app.uninstall_pwa(self.aid))

    def closeEvent(self, ev):
        try:
            self.tab.cleanup()
        except Exception:
            log.debug("tab cleanup", exc_info=True)
        super().closeEvent(ev)


def pwa_contrast(color):
    c = QColor(color)
    return "#111111" if (0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()) > 160 else "#ffffff"
