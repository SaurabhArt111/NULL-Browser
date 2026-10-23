"""Menus of a browser window."""

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QMenu, QToolButton, QWidget, QWidgetAction)

from ..constants import SCHEME
from ..core import crash
from .tips import tip


class MenusMixin:
    """Toolbar pop-up menus and the main menu."""

    def _popup_menu(self):
        t = self.current()
        m = QMenu(self)
        m.addAction(f"Pop-ups were blocked on this page ({t.blocked_popups})").setEnabled(False)
        origin = t.current_origin
        m.addAction("Always allow pop-ups from this site", lambda: (self.app.perms.set_site(origin, "popups", "allow", self.private), self.app.apply_site_policies(), t.reload()))
        m.addAction("Continue blocking", lambda: setattr(t, "blocked_popups", 0) or self.update_security())
        m.exec(self.omni.popup_chip.mapToGlobal(self.omni.popup_chip.rect().bottomLeft()))

    def _zoom_menu(self):
        t = self.current()
        m = QMenu(self)
        m.addAction("Zoom in", lambda: t.zoom_step(1))
        m.addAction("Zoom out", lambda: t.zoom_step(-1))
        m.addAction("Reset to 100%", lambda: t.set_zoom(1.0))
        m.exec(self.omni.zoom_chip.mapToGlobal(self.omni.zoom_chip.rect().bottomLeft()))

    def _shield_menu(self):
        t = self.current()
        host = t.real_url().host()
        m = QMenu(self)
        m.addAction(f"{self.app.adblock.stats_for(host)} ads and trackers blocked here").setEnabled(False)
        allowed = self.app.adblock.is_allowed(host)
        m.addAction("Allow ads on this site" if not allowed else "Block ads on this site again",
                    lambda: (self.app.adblock.set_allowed(host, not allowed), self.app.refresh_shield(), t.reload()))
        m.addAction("Ad blocker settings", lambda: self.open_url(f"{SCHEME}://settings/privacy"))
        m.exec(self.omni.shield_chip.mapToGlobal(self.omni.shield_chip.rect().bottomLeft()))

    def _tab_menu_action(self, name, i):
        t = self.tabs[i] if 0 <= i < len(self.tabs) else None
        if name == "new":
            self.new_tab()
        elif name == "reopen":
            self.reopen_closed_tab()
        elif t is None:
            return
        elif name == "reload":
            t.reload()
        elif name == "duplicate":
            self.new_tab(t.real_url().toString(), index=i + 1)
        elif name == "new_window":
            self.move_tab_to_new_window(i)
        elif name == "pin":
            t.pinned = not t.pinned
            self._decorate(t)
            self._tab_title(t)
            self._schedule_session()
        elif name == "mute":
            self._toggle_mute_index(i)
        elif name == "close":
            self.close_tab(t)
        elif name == "close_others":
            for o in [x for x in self.tabs if x is not t]:
                self.close_tab(o)
        elif name == "close_right":
            for o in self.tabs[i + 1:]:
                self.close_tab(o)

    def tab_search_menu(self):
        m = QMenu(self)
        for i, t in enumerate(self.tabs):
            a = m.addAction(self.tabbar.tabIcon(i), (t.title() or "Tab")[:60])
            a.triggered.connect(lambda _=False, k=i: self.tabbar.setCurrentIndex(k))
        m.exec(self.tabsearch_btn.mapToGlobal(QPoint(0, self.tabsearch_btn.height() + 4)))

    def show_main_menu(self):
        t = self.current()
        m = QMenu(self)
        A = lambda text, fn, sc=None, ic=None, menu=None: self._menu_item(menu or m, text, fn, sc, ic)
        A("New tab", lambda: self.new_tab(), "Ctrl+T", "plus")
        A("New window", lambda: self.app.open_window(None, False), "Ctrl+N")
        A("New InPrivate window", lambda: self.app.open_window(None, True), "Ctrl+Shift+N", "eye_off")
        m.addSeparator()
        A("History", lambda: self.open_url(f"{SCHEME}://history"), "Ctrl+H", "history")
        A("Downloads", lambda: self.open_url(f"{SCHEME}://downloads"), "Ctrl+J", "download")
        bm = m.addMenu(self.icon("bookmark"), "Bookmarks")
        A("Bookmark this tab…", self.toggle_bookmark, "Ctrl+D", "star", bm)
        A("Show bookmarks bar", lambda: self.app.settings.set("show_bookmarks_bar", not self.app.settings.get("show_bookmarks_bar")), "Ctrl+Shift+B", None, bm).setCheckable(True)
        bm.actions()[-1].setChecked(bool(self.app.settings.get("show_bookmarks_bar")))
        A("Bookmark manager", lambda: self.open_url(f"{SCHEME}://bookmarks"), "Ctrl+Shift+O", "bookmark", bm)
        bm.addSeparator()
        for b in self.app.db.bookmarks()[:15]:
            a = bm.addAction(self._fav_icon(b["url"]), (b["title"] or b["url"])[:50])
            a.triggered.connect(lambda _=False, u=b["url"]: self.open_url(u, new_tab=False))
        m.addSeparator()
        zw = QWidgetAction(m)
        zr = QWidget()
        zl = QHBoxLayout(zr)
        zl.setContentsMargins(14, 2, 8, 2)
        zl.addWidget(QLabel("Zoom"), 1)
        for txt, fn in (("−", lambda: t.zoom_step(-1)), ("+", lambda: t.zoom_step(1))):
            b = QToolButton()
            b.setText(txt)
            b.setFixedSize(30, 28)
            b.clicked.connect(lambda _=False, f=fn: (f(), lbl.setText(f"{round(t.page.zoomFactor() * 100)}%")))
            zl.addWidget(b)
            if txt == "−":
                lbl = QLabel(f"{round(t.page.zoomFactor() * 100)}%")
                lbl.setFixedWidth(46)
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                zl.addWidget(lbl)
        fs = QToolButton()
        fs.setIcon(self.icon("fullscreen", size=16))
        tip(fs, "Full screen", "Hide the toolbars and fill the screen", "F11")
        fs.clicked.connect(lambda: (m.close(), self.toggle_fullscreen()))
        zl.addWidget(fs)
        zw.setDefaultWidget(zr)
        m.addAction(zw)
        m.addSeparator()
        A("Print…", t.print_page, "Ctrl+P", "print")
        A("Find in page…", t.show_find, "Ctrl+F", "search")
        A("Save page as…", t.save_page, "Ctrl+S", "download")
        A("Save as PDF…", t.save_pdf, None, "file")
        tools = m.addMenu(self.icon("tool"), "More tools")
        A("Developer tools", t.toggle_devtools, "F12", "code", tools)
        A("View page source", t.view_source, "Ctrl+U", None, tools)
        A("Tab search", self.tab_search_menu, "Ctrl+Shift+A", None, tools)
        A("Clear browsing data…", lambda: self.open_url(f"{SCHEME}://history?clear=1"), "Ctrl+Shift+Del", "trash", tools)
        A("Logs & errors", lambda: self.open_url(f"{SCHEME}://logs"), None, "info", tools)
        A("Null Search engine", lambda: self.open_url(self.app.engine.info()["url"]), None, "search", tools)
        m.addSeparator()
        A("Settings", lambda: self.open_url(f"{SCHEME}://settings"), "Ctrl+,", "settings")
        A("About Null Browser", lambda: self.open_url(f"{SCHEME}://about"), None, "info")
        m.addSeparator()
        A("Exit", self.app.quit_all, None, "close")
        pos = self.menu_btn.mapToGlobal(self.menu_btn.rect().bottomLeft())
        pos.setX(pos.x() + self.menu_btn.width() - m.sizeHint().width())
        m.exec(pos)
        m.deleteLater()

    def _menu_item(self, menu, text, fn, shortcut=None, ic=None):
        a = QAction(text, menu)
        if ic:
            a.setIcon(self.icon(ic))
        if shortcut:
            a.setText(f"{text}\t{shortcut}")
        a.triggered.connect(lambda *_: crash.guarded(fn)())
        menu.addAction(a)
        return a
