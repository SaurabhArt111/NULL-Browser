"""Toolbar parts for the Google account, the built-in VPN and installed web apps (PWA) of a browser window."""
import logging
import os

from PyQt6.QtCore import QPoint, QRectF, QSize, Qt
from PyQt6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import QMenu

from ..constants import SCHEME
from ..core import crash
from ..engine.pagescripts import WORLD
from .tips import tip

log = logging.getLogger("null.window.apps")


def avatar_pixmap(path, letter, color, size=24, dpr=2.0):
    """Round profile picture: the saved Google photo, or the first letter on the accent colour."""
    px = int(size * dpr)
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    clip = QPainterPath()
    clip.addEllipse(QRectF(0, 0, px, px))
    p.setClipPath(clip)
    src = QPixmap(path) if path and os.path.isfile(path) else QPixmap()
    if not src.isNull():
        p.drawPixmap(0, 0, src.scaled(px, px, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation))
    else:
        p.fillRect(0, 0, px, px, QColor(color))
        p.setPen(QColor("#ffffff"))
        f = QFont()
        f.setPixelSize(int(px * 0.52))
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(0, 0, px, px), Qt.AlignmentFlag.AlignCenter, (letter or "?")[:1].upper())
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


class WindowAppsMixin:
    """Profile button, VPN button, install chip and the Apps menu."""

    # ---- build (called once from MainWindow.__init__ after the toolbar buttons exist) ---------------------------------
    def build_account_buttons(self):
        mk = self._tbtn
        self.vpn_btn = mk(("VPN is on", "All traffic from this browser goes through your VPN server. Click for options"), self.show_vpn_menu)
        self.vpn_btn.hide()
        self.account_btn = mk(("Google account", "Sign in with Google and manage your profile"), self.show_account_menu)
        self.account_btn.setIconSize(QSize(24, 24))
        self.omni.install_chip.clicked.connect(self.install_current)
        self.app.accountChanged.connect(self.refresh_account_button)
        self.app.pwaChanged.connect(self.update_install_chip)
        self.refresh_account_button()
        self.refresh_vpn_button()

    # ---- account -------------------------------------------------------------------------------------------------------
    def refresh_account_button(self):
        info = self.app.account_info()
        if self.private:
            self.account_btn.setIcon(self.icon("eye_off", size=18))
            tip(self.account_btn, "InPrivate", "You are browsing InPrivate. Nothing from this window is saved")
            return
        if info["signed_in"]:
            name = info.get("name") or info["email"]
            self.account_btn.setIcon(QIcon(avatar_pixmap(self.app.avatar_path(), name, self.accent)))
            tip(self.account_btn, name, info["email"])
        else:
            self.account_btn.setIcon(self.icon("user", size=20))
            tip(self.account_btn, "Sign in", "Sign in with your Google account. The sign-in stays even after you clear browsing data")

    def show_account_menu(self):
        info = self.app.account_info()
        m = QMenu(self)
        A = lambda text, fn, ic=None, menu=None: self._menu_item(menu or m, text, fn, None, ic)
        if self.private:
            m.addAction("You are browsing InPrivate").setEnabled(False)
            A("Close InPrivate window", self.close, "close")
        elif info["signed_in"]:
            head = m.addAction(QIcon(avatar_pixmap(self.app.avatar_path(), info.get("name") or info["email"], self.accent, 36)),
                               f"{info.get('name') or info['email']}\n{info['email']}")
            head.setEnabled(False)
            m.addSeparator()
            A("Manage your Google Account", lambda: self.open_url("https://myaccount.google.com/"), "user")
            A("Refresh account", lambda: self.app.refresh_identity(), "sync")
            keep = QAction("Stay signed in after clearing data", m)
            keep.setCheckable(True)
            keep.setChecked(info["keep_on_clear"])
            keep.triggered.connect(lambda on: self.app.settings.set("google_keep_signed_in", bool(on)))
            m.addAction(keep)
            m.addSeparator()
            A("Sign out", self.app.sign_out, "power")
        else:
            m.addAction("Sign in to use your Google account in Null Browser").setEnabled(False)
            A("Sign in with Google…", self.app.begin_sign_in, "user")
        m.addSeparator()
        A("Account settings", lambda: self.open_url(f"{SCHEME}://settings/account"), "settings")
        pos = self.account_btn.mapToGlobal(QPoint(self.account_btn.width() - m.sizeHint().width(), self.account_btn.height() + 2))
        m.exec(pos)
        m.deleteLater()

    # ---- vpn -----------------------------------------------------------------------------------------------------------
    def refresh_vpn_button(self):
        v = self.app.vpn
        on = v.enabled
        self.vpn_btn.setVisible(on)
        if on:
            s = v.active() or {}
            self.vpn_btn.setIcon(self.icon("vpn", color=self.accent, size=20))
            tip(self.vpn_btn, "VPN is on", f"Traffic goes through {s.get('name', 'your VPN server')}. If the server stops answering, pages will not load: nothing leaks.")

    def show_vpn_menu(self):
        v = self.app.vpn
        s = v.active() or {}
        m = QMenu(self)
        m.addAction(f"Connected through {s.get('name', '?')}").setEnabled(False)
        self._menu_item(m, "Turn VPN off (restarts the browser)", lambda: self.app.vpn_set_enabled(False), None, "power")
        self._menu_item(m, "VPN settings", lambda: self.open_url(f"{SCHEME}://settings/vpn"), None, "settings")
        m.exec(self.vpn_btn.mapToGlobal(QPoint(0, self.vpn_btn.height() + 2)))
        m.deleteLater()

    # ---- install chip ---------------------------------------------------------------------------------------------------
    def probe_installable(self, tab):
        """After a page finished loading: does it declare a web app manifest?"""
        tab.installable = False
        if not self.app.can_install(tab):
            self.update_install_chip()
            return
        from ..app_pwa import HAS_MANIFEST_JS

        def got(v):
            tab.installable = bool(v)
            if tab is self.current():
                self.update_install_chip()
        try:
            tab.page.runJavaScript(HAS_MANIFEST_JS, WORLD, got)
        except Exception:
            log.debug("manifest probe failed", exc_info=True)

    def update_install_chip(self):
        t = self.current()
        show = False
        label = "Install"
        if t is not None and getattr(t, "installable", False) and self.app.can_install(t):
            existing = self.app.pwa.find_for_url(t.page.url().toString())
            show = True
            label = "Open app" if existing else "Install"
        chip = self.omni.install_chip
        chip.setVisible(show)
        chip.setText(" " + label)
        chip.setIcon(self.icon("install", color=self.accent, size=16))

    @crash.guarded
    def install_current(self):
        t = self.current()
        if t is not None:
            self.app.install_from_tab(t, self)

    # ---- apps menu ---------------------------------------------------------------------------------------------------------
    def build_apps_menu(self, parent_menu):
        sub = parent_menu.addMenu(self.icon("apps"), "Apps")
        t = self.current()
        if t is not None and self.app.can_install(t):
            existing = self.app.pwa.find_for_url(t.page.url().toString())
            self._menu_item(sub, "Open this site as an app" if existing else "Install this site as an app…", self.install_current, None, "install")
            sub.addSeparator()
        apps = self.app.pwa.public()
        if not apps:
            sub.addAction("No apps installed yet").setEnabled(False)
        for a in apps:
            icon_path = self.app.pwa.icon_path(a["id"])
            act = sub.addAction(QIcon(icon_path) if icon_path and os.path.isfile(icon_path) else self.icon("globe"), a["name"])
            act.triggered.connect(lambda _=False, i=a["id"]: self.app.open_pwa(i))
        sub.addSeparator()
        self._menu_item(sub, "Manage apps", lambda: self.open_url(f"{SCHEME}://settings/apps"), None, "settings")
        return sub
