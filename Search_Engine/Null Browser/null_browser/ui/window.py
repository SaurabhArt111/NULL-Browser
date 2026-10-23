"""Main browser window: tab strip, toolbar, omnibox, bookmarks bar, menus and shortcuts."""
import logging
import re

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QKeySequence
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMainWindow, QProgressBar, QStackedWidget, QVBoxLayout, QWidget)

from ..constants import APP_NAME, SCHEME
from ..core import crash
from ..core.search import display_url
from . import icons, native, theme, winframe
from .omnibox import Omnibox
from .popups import DownloadsPopup, InfoBar, SiteInfoPopup
from .tab import Tab
from .tabbar import TabStrip, TitleStrip, WindowControls
from .tips import tip, tip_html
from .widgets import HoverToolButton
from .window_bookmarks import BookmarksBarMixin
from .window_dragdrop import TabTransferMixin
from .window_frame import WindowFrameMixin
from .window_menus import MenusMixin

log = logging.getLogger("null.window")


class MainWindow(BookmarksBarMixin, WindowFrameMixin, TabTransferMixin, MenusMixin, QMainWindow):
    """The browser window. Tab handling, chrome state and actions live here; see the window_*.py mixins for the rest."""
    closedSignal = pyqtSignal(object)

    def __init__(self, app, private=False):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.app, self.private = app, private
        self.profile = app.profile_for(private)           # creates the off-the-record profile on first use
        self.closed_tabs = []                 # (url, index, pinned) most recent last
        self.fullscreen_tab = False
        self._session_timer = QTimer(self, singleShot=True, interval=700, timeout=lambda: app.save_session())
        self.setWindowTitle(APP_NAME + (" (InPrivate)" if private else ""))
        self.setWindowIcon(icons.app_icon())
        self.resize(1280, 840)
        self.setMinimumSize(520, 360)
        self.setAcceptDrops(True)
        # Merged title bar: the OS caption is removed and the tab strip + window buttons do its job (like Chrome).
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowMinimizeButtonHint
                            | Qt.WindowType.WindowMaximizeButtonHint | Qt.WindowType.WindowSystemMenuHint)
        self.setMouseTracking(True)
        self._resize_edges = Qt.Edge(0)
        self._hint = None
        self._native_frame = False                        # True once Windows treats us as a real resizable window
        self._live_resize = False                         # True while Windows runs the drag-resize / move loop
        self._bg_brush = None                             # GDI brush the native frame paints uncovered areas with
        self.snap_layouts = False                         # Windows 11 Snap Layouts flyout on the maximise button
        self._bm_timer = QTimer(self, singleShot=True, interval=70, timeout=lambda: self.refresh_bookmarks())
        self._update_border()

        root = QWidget()
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # --- merged title bar: [v][tab][tab][+] ......drag area...... [-][o][x] ----------------------------
        self.strip = TitleStrip(self)
        sh = QHBoxLayout(self.strip)
        sh.setContentsMargins(6, 0, 0, 0)
        sh.setSpacing(0)
        self.tabsearch_btn = HoverToolButton(self._hover_colors, radius=12)
        self.tabsearch_btn.setObjectName("tabsearch")
        self.tabsearch_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tip(self.tabsearch_btn, "Search tabs", "See and jump to any open tab", "Ctrl+Shift+A")
        self.tabsearch_btn.clicked.connect(self.tab_search_menu)
        self.tabbar = TabStrip(self)
        self.tabbar.reserved = 330
        self.tabbar.currentChanged.connect(self._current_changed)
        self.tabbar.tabMoved.connect(self._tab_moved)
        self.tabbar.closeRequested.connect(self.close_tab_index)
        self.tabbar.newTabRequested.connect(lambda: self.new_tab())
        self.tabbar.menuAction.connect(self._tab_menu_action)
        self.tabbar.audioToggled.connect(self._toggle_mute_index)
        self.newtab_btn = HoverToolButton(self._hover_colors, radius=13)
        self.newtab_btn.setObjectName("newtab")
        self.newtab_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tip(self.newtab_btn, "New tab", "Open a blank tab", "Ctrl+T")
        self.newtab_btn.clicked.connect(lambda: self.new_tab())
        self.private_badge = QLabel("InPrivate")
        self.private_badge.setObjectName("privatebadge")
        self.private_badge.setVisible(private)
        tip(self.private_badge, "InPrivate window", "History, cookies and site data from this window are not saved")
        self.wc = WindowControls(self)
        sh.addWidget(self.tabsearch_btn, 0, Qt.AlignmentFlag.AlignTop)
        sh.addWidget(self.tabbar)
        sh.addWidget(self.newtab_btn, 0, Qt.AlignmentFlag.AlignTop)
        sh.addStretch(1)
        sh.addWidget(self.private_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        sh.addSpacing(8)
        sh.addWidget(self.wc, 0, Qt.AlignmentFlag.AlignTop)
        v.addWidget(self.strip)
        self._drop_hint = QFrame(self.strip)
        self._drop_hint.setObjectName("drophint")
        self._drop_hint.hide()

        # --- toolbar ---------------------------------------------------------------------
        self.toolbar = QWidget()
        self.toolbar.setObjectName("toolbar")
        th = QHBoxLayout(self.toolbar)
        th.setContentsMargins(8, 4, 8, 4)
        th.setSpacing(2)
        mk = lambda tip, fn: self._tbtn(tip, fn)
        self.back_btn = mk(("Back", "Go to the previous page", "Alt+Left"), lambda: self.cur_do("back"))
        self.fwd_btn = mk(("Forward", "Go to the next page", "Alt+Right"), lambda: self.cur_do("forward"))
        self.reload_btn = mk(("Reload", "Load this page again", "Ctrl+R"), self.reload_or_stop)
        self.home_btn = mk(("Home", "Open your home page", "Alt+Home"), self.go_home)
        self.omni = Omnibox(self)
        self.omni.navigate.connect(self.navigate_text)
        self.omni.securityClicked.connect(self.show_site_info)
        self.omni.starClicked.connect(self.toggle_bookmark)
        self.omni.focusChanged.connect(self._omni_focus)
        self.omni.popup_chip.clicked.connect(self._popup_menu)
        self.omni.zoom_chip.clicked.connect(self._zoom_menu)
        self.omni.shield_chip.clicked.connect(self._shield_menu)
        self.dl_btn = mk(("Downloads", "See files you have downloaded", "Ctrl+J"), self.show_downloads_popup)
        self.dl_btn.hide()
        self.menu_btn = mk(("Menu", "Customize and control Null Browser: history, bookmarks, settings and more"), self.show_main_menu)
        for w in (self.back_btn, self.fwd_btn, self.reload_btn, self.home_btn):
            th.addWidget(w)
        th.addSpacing(4)
        th.addWidget(self.omni, 1)
        th.addSpacing(4)
        th.addWidget(self.dl_btn)
        th.addWidget(self.menu_btn)
        v.addWidget(self.toolbar)
        self.loadbar = QProgressBar()
        self.loadbar.setObjectName("loadbar")
        self.loadbar.setTextVisible(False)
        self.loadbar.setRange(0, 100)
        self.loadbar.setFixedHeight(3)
        v.addWidget(self.loadbar)                       # always shown: hiding / showing it resized the page area on every load (visible jump)

        # --- bookmarks bar + info bars ---------------------------------------------------------
        self.bmbar = QWidget()
        self.bmbar.setObjectName("bookmarkbar")
        self.bm_layout = QHBoxLayout(self.bmbar)
        self.bm_layout.setContentsMargins(8, 2, 8, 2)
        self.bm_layout.setSpacing(2)
        v.addWidget(self.bmbar)
        self.infobars = QVBoxLayout()
        self.infobars.setSpacing(0)
        v.addLayout(self.infobars)

        self.stack = QStackedWidget()
        v.addWidget(self.stack, 1)
        self.tabs = []                            # widgets in tab order (mirrors tabbar)

        self._spin_timer = QTimer(self, interval=90, timeout=self._spin)
        self._build_actions()
        self.restyle()
        app.themeChanged.connect(self.restyle)
        self.refresh_chrome()
        self.refresh_bookmarks()
        self.app.downloads.changed.connect(self._downloads_changed)
        self._downloads_changed()
        self._ensure_native_frame()

    # ===================================================================== plumbing
    @property
    def accent(self):
        return self.app.accent

    @property
    def pal(self):
        return self.app.pal(self.private)

    def icon(self, name, color=None, size=20):
        return self.app.icon(name, color=color, size=size, private=self.private)

    def _hover_colors(self):
        p = self.pal
        return p["hover"], p["press"]

    def _tbtn(self, tipspec, fn):
        b = HoverToolButton(self._hover_colors)
        tip(b, *tipspec)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.setIconSize(QSize(20, 20))
        b.setFixedSize(34, 34)
        b.clicked.connect(lambda *_: crash.guarded(fn)())
        return b

    def current(self):
        i = self.tabbar.currentIndex()
        return self.tabs[i] if 0 <= i < len(self.tabs) else None

    def index_of(self, tab):
        try:
            return self.tabs.index(tab)
        except ValueError:
            return -1

    # names used by BrowserApp
    current_tab = current

    def add_tab(self, url=None, background=False):
        return self.new_tab(url, background=background)

    def restore_state(self, ws):
        """Recreate tabs from a saved session. Only the selected tab loads now; the rest load when first shown."""
        entries = [e for e in ws.get("tabs", []) if isinstance(e, dict) and e.get("url")]
        cur = ws.get("current", 0)
        cur = cur if isinstance(cur, int) and 0 <= cur < len(entries) else 0
        for i, e in enumerate(entries):
            self.new_tab(None, background=True, pinned=bool(e.get("pinned")), lazy=(str(e["url"]), str(e.get("title") or "")))
        if not self.tabs:
            self.new_tab(f"{SCHEME}://newtab")
            return
        self.tabbar.setCurrentIndex(cur)
        self._current_changed(cur)

    def show_toast(self, text, ms=5000):
        """Small non-blocking message at the bottom of the window."""
        old = getattr(self, "_toast", None)
        if old is not None:
            old.deleteLater()
        p = self.pal
        lab = QLabel(text, self.centralWidget())
        lab.setWordWrap(True)
        lab.setStyleSheet(f"background:{p['tip']};color:{p['tip_text']};border-radius:10px;padding:10px 16px;font-size:13px;")
        lab.setMaximumWidth(min(620, max(260, self.width() - 60)))
        lab.adjustSize()
        lab.move((self.width() - lab.width()) // 2, self.height() - lab.height() - 36)
        lab.show()
        lab.raise_()
        self._toast = lab
        QTimer.singleShot(ms, lambda l=lab: l.deleteLater() if l is getattr(self, "_toast", None) else None)

    def offer_safe_mode(self):
        if getattr(self, "_safe_offer", None) is not None:
            return
        def clear():
            self._safe_offer = None
        self._safe_offer = self.add_infobar(
            "Null Browser has hit several errors in a short time. Safe mode turns off the ad blocker, API gate and session restore.",
            [("Restart in safe mode", lambda: self.app.restart(safe=True)), ("Keep going", lambda: None)], on_close=clear)

    def cur_do(self, what):
        t = self.current()
        if not t:
            return
        {"back": t.page.triggerAction, "forward": t.page.triggerAction}[what](
            t.page.WebAction.Back if what == "back" else t.page.WebAction.Forward)

    def restyle(self):
        a = self.app
        p = self.pal
        if self.private:                                   # window-level palette + stylesheet override the app's
            self.setPalette(theme.palette(p, a.accent))
            self.setStyleSheet(theme.stylesheet(p, a.accent))
        else:
            self.setStyleSheet("")
        for name, b in (("back", self.back_btn), ("forward", self.fwd_btn), ("home", self.home_btn), ("download", self.dl_btn), ("more", self.menu_btn)):
            b.setIcon(self.icon(name))
        self._set_reload_icon(False)
        self.newtab_btn.setIcon(self.icon("plus", size=18))
        self.newtab_btn.setIconSize(QSize(16, 16))
        self.tabsearch_btn.setIcon(self.icon("tab_search", size=16))
        self.tabsearch_btn.setIconSize(QSize(14, 14))
        self.wc.refresh()
        self.omni.restyle()
        self.tabbar.restyle()
        for t in self.tabs:
            t.find.restyle()
        self.private_badge.setVisible(self.private)
        native.set_dark_titlebar(self, p["dark"])
        winframe.set_background(self, QColor(p["bar"]))
        self.refresh_bookmarks()
        self.update_toolbar_state()

    def refresh_chrome(self):
        s = self.app.settings
        self.bmbar.setVisible(bool(s.get("show_bookmarks_bar")) and not self.fullscreen_tab)
        self.home_btn.setVisible(bool(s.get("show_home_button")))

    # ===================================================================== tabs
    def new_tab(self, url=None, background=False, index=None, request=None, pinned=False, focus_omnibox=True, lazy=None):
        try:
            tab = Tab(self.app, self.profile, self.private)
            tab.pinned = pinned
            self._wire_tab(tab)
            i = len(self.tabs) if index is None else max(0, min(index, len(self.tabs)))
            self.tabs.insert(i, tab)
            self.stack.insertWidget(i, tab)
            self.tabbar.blockSignals(True)
            self.tabbar.insertTab(i, self.icon("globe", size=16), "New Tab")
            self.tabbar.blockSignals(False)
            self._decorate(tab)
            if lazy:                                         # (url, title): load when first shown
                tab.lazy_url, tab.lazy_title = lazy
                self._tab_title(tab)
            elif request is not None:
                request.openIn(tab.page)
            elif url:
                tab.load(url)
            else:
                tab.load(f"{SCHEME}://newtab")
            if not background:
                self.tabbar.setCurrentIndex(i)
                self._current_changed(i)
            self._schedule_session()
            return tab
        except Exception:
            crash.log.exception("new_tab")
            return None

    def _wire_tab(self, tab):
        tab.titleChanged.connect(self._tab_title)
        tab.urlChanged.connect(self._tab_url)
        tab.iconChanged.connect(self._tab_icon)
        tab.loadingChanged.connect(self._tab_loading)
        tab.progressChanged.connect(self._tab_progress)
        tab.audioChanged.connect(lambda t=tab: self._decorate(t))
        tab.securityChanged.connect(lambda t=tab: self._tab_security(t))
        tab.zoomChanged.connect(lambda t=tab: self._tab_security(t))
        tab.popupBlocked.connect(lambda t=tab: self._tab_security(t))
        tab.openTab.connect(self._open_tab_signal)
        tab.openWindow.connect(lambda u, p: self.app.open_window(u, p))
        tab.closeRequested.connect(self.close_tab)
        tab.fullscreenToggled.connect(self.set_page_fullscreen)
        tab.focusOmnibox.connect(lambda t=tab: self.omni.focus_and_select() if t is self.current() else None)

    def _open_tab_signal(self, url, background, request):
        src = self.sender()
        i = self.index_of(src) + 1 if src in self.tabs else None
        self.new_tab(url if request is None else None, background, i, request, focus_omnibox=False)

    def _decorate(self, tab):
        i = self.index_of(tab)
        if i < 0:
            return
        audible = tab.page.recentlyAudible()
        self.tabbar.decorate(i, tab.pinned, audible, tab.page.isAudioMuted())

    def close_tab_index(self, i):
        if 0 <= i < len(self.tabs):
            self.close_tab(self.tabs[i])

    def close_tab(self, tab):
        i = self.index_of(tab)
        if i < 0:
            return
        url = tab.real_url().toString()
        if not self.private and url and not url.startswith(f"{SCHEME}://newtab") and tab.page.url().scheme() != "about":
            self.closed_tabs.append((url, i, tab.pinned))
            del self.closed_tabs[:-25]
        if len(self.tabs) == 1:
            self.close()                                  # closing the last tab closes the window
            return
        was_current = i == self.tabbar.currentIndex()
        self.tabbar.blockSignals(True)
        self.tabs.pop(i)
        self.tabbar.removeTab(i)
        self.tabbar.blockSignals(False)
        self.stack.removeWidget(tab)
        tab.cleanup()
        tab.deleteLater()
        self.tabbar.clear_loading()
        for t in self.tabs:
            if t.loading:
                self.tabbar.set_loading(self.index_of(t), True)
        if was_current:
            self._current_changed(self.tabbar.currentIndex())
        self._schedule_session()

    def reopen_closed_tab(self):
        if self.closed_tabs:
            url, i, pinned = self.closed_tabs.pop()
            self.new_tab(url, index=i, pinned=pinned)

    def _current_changed(self, i):
        if not (0 <= i < len(self.tabs)):
            return
        self.stack.setCurrentIndex(i)
        t = self.tabs[i]
        t.activate()
        self._sync_chrome()
        self._schedule_session()
        if t.is_internal() and t.page.url().host() == "newtab":
            self.omni.focus_and_select()

    def _tab_moved(self, frm, to):
        t = self.tabs.pop(frm)
        self.tabs.insert(to, t)
        w = self.stack.widget(frm)
        self.stack.removeWidget(w)
        self.stack.insertWidget(to, w)
        self.stack.setCurrentIndex(self.tabbar.currentIndex())
        self._schedule_session()

    def _tab_title(self, tab):
        i = self.index_of(tab)
        if i < 0:
            return
        title = tab.title()
        self.tabbar.setTabText(i, "" if tab.pinned else title)
        pre = "💤 " if tab.discarded else ""
        self.tabbar.setTabToolTip(i, tip_html(f"{pre}{title}", display_url(tab.real_url().toString())))
        if tab is self.current():
            self.setWindowTitle(f"{title} - {APP_NAME}" + (" (InPrivate)" if self.private else ""))
        self._schedule_session()

    def _tab_url(self, tab):
        if tab is self.current():
            self.update_omnibox()
            self.update_toolbar_state()
        self._schedule_session()

    def _tab_icon(self, tab):
        i = self.index_of(tab)
        if i < 0 or tab.loading:
            return
        ic = tab.page.icon()
        if tab.is_internal() and tab.page.url().host() != "error":
            ic = self.icon("null", color=self.accent, size=16)
        elif ic.isNull():
            ic = self.icon("globe", size=16)
        self.tabbar.setTabIcon(i, ic)

    def _tab_loading(self, loading):
        tab = self.sender()
        i = self.index_of(tab)
        if i < 0:
            return
        self.tabbar.set_loading(i, loading)
        if not loading:
            self._tab_icon(tab)
            self._tab_title(tab)
        if tab is self.current():
            self.update_toolbar_state()
            if not loading:
                self.loadbar.setValue(0)

    def _tab_progress(self, p):
        if self.sender() is self.current():
            self.loadbar.setValue(p if p < 100 else 0)

    def _tab_security(self, tab):
        if tab is self.current():
            self.update_security()

    def _spin(self):
        pass

    # ===================================================================== chrome state
    def _sync_chrome(self):
        t = self.current()
        if not t:
            return
        self.update_omnibox()
        self.update_toolbar_state()
        self.update_security()
        self.loadbar.setValue(t.progress if t.loading and t.progress < 100 else 0)
        self._tab_title(t)

    def update_omnibox(self):
        t = self.current()
        if not t:
            return
        u = t.real_url()
        if u.scheme() == SCHEME and u.host() == "newtab":
            text = ""
        elif u.scheme() in ("http", "https"):
            text = display_url(u.toString())
        else:
            text = u.toDisplayString()
        self.omni.set_display(text)
        self.update_star()

    def revert_omnibox(self):
        self.omni.edit.blockSignals(True)
        self.omni.edit.clear()
        self.omni.edit.blockSignals(False)
        self.update_omnibox()
        t = self.current()
        if t:
            t.view.setFocus()

    def _omni_focus(self, focused):
        if not focused:
            self.update_omnibox()
        else:
            t = self.current()
            if t:
                self.omni.edit.setText(t.real_url().toString() if t.real_url().scheme() in ("http", "https") else self.omni.edit.text())
                if t.real_url().scheme() in ("http", "https"):
                    self.omni.edit.selectAll()

    def update_toolbar_state(self):
        t = self.current()
        if not t:
            return
        h = t.page.history()
        self.back_btn.setEnabled(h.canGoBack())
        self.fwd_btn.setEnabled(h.canGoForward())
        self._set_reload_icon(t.loading)

    def _set_reload_icon(self, loading):
        self.reload_btn.setIcon(self.icon("stop" if loading else "reload"))
        if loading:
            tip(self.reload_btn, "Stop", "Stop loading this page", "Esc")
        else:
            tip(self.reload_btn, "Reload", "Load this page again", "Ctrl+R")

    def update_security(self):
        t = self.current()
        if not t:
            return
        u = t.real_url()
        s = u.scheme()
        p = self.pal
        sec = self.omni.sec
        sec.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        sec.setText("")
        if t.cert_failed:
            sec.setIcon(self.icon("alert", color=p["danger"], size=16))
            sec.setText(" Not secure")
            sec.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        elif s == "https":
            sec.setIcon(self.icon("lock", color=p["text"], size=16))
        elif s == "http":
            sec.setIcon(self.icon("alert", color=p["danger"], size=16))
            sec.setText(" Not secure")
            sec.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        elif s == SCHEME:
            sec.setIcon(self.icon("null", color=self.accent, size=16))
        elif s == "file":
            sec.setIcon(self.icon("file", color=p["text"], size=16))
            sec.setText(" File")
            sec.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        else:
            sec.setIcon(self.icon("info", size=16))
        # popup chip
        self.omni.popup_chip.setVisible(t.blocked_popups > 0)
        z = round(t.page.zoomFactor() * 100)
        self.omni.zoom_chip.setVisible(z != 100)
        self.omni.zoom_chip.setText(f"{z}%")
        n = self.app.adblock.stats_for(u.host()) if s in ("http", "https") else 0
        self.omni.shield_chip.setVisible(n > 0)
        self.omni.shield_chip.setIcon(self.icon("shield", color=self.accent, size=16))
        self.omni.shield_chip.setText(str(n))
        self.update_star()


    def refresh_shield(self):
        self.update_security()

    # ===================================================================== navigation
    def navigate_text(self, text, new_tab=False):
        t = self.current()
        url, is_search = self.app.resolve_text(text)
        if not url:
            return
        if (not is_search and self.app.settings.get("https_first") and url.startswith("https://")
                and not re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://", text.strip()) and not re.match(r"^[\w.\-]+:\d+", text.strip())):
            fallback = "http://" + url[len("https://"):]
        else:
            fallback = ""
        if new_tab or t is None:
            t = self.new_tab(None, background=False)
        t._upgraded = False
        t.http_fallback = fallback
        t.typed_url = "" if is_search else url
        t.load(url)
        t.view.setFocus()

    def open_url(self, url, new_tab=True, background=False):
        if new_tab or not self.current():
            return self.new_tab(url, background=background)
        self.current().load(url)
        return self.current()

    def go_home(self):
        self.open_url(self.app.settings.get("homepage") or f"{SCHEME}://newtab", new_tab=False)

    def reload_or_stop(self):
        t = self.current()
        if t:
            t.stop() if t.loading else t.reload()

    def focus_omnibox(self):
        self.omni.focus_and_select()


    # ===================================================================== popups & menus
    def show_site_info(self):
        t = self.current()
        if t:
            SiteInfoPopup(self, t).show_under(self.omni.sec)

    def show_downloads_popup(self):
        DownloadsPopup(self).show_under(self.dl_btn, align_right=True)

    def _downloads_changed(self):
        self.dl_btn.setVisible(bool(self.app.downloads.list()))
        n = self.app.downloads.active_count()
        tip(self.dl_btn, "Downloads", f"{n} download{'s' if n != 1 else ''} in progress" if n else "See files you have downloaded", "Ctrl+J")


    def tab_muted(self, i, bar=None):
        return 0 <= i < len(self.tabs) and self.tabs[i].page.isAudioMuted()

    def _toggle_mute_index(self, i):
        if 0 <= i < len(self.tabs):
            t = self.tabs[i]
            t.user_muted = not t.page.isAudioMuted()
            t.page.setAudioMuted(t.user_muted)
            self._decorate(t)


    # ===================================================================== shortcuts
    def _build_actions(self):
        def add(seq, fn):
            a = QAction(self)
            a.setShortcuts([QKeySequence(s) for s in seq.split("|")])
            a.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            a.triggered.connect(lambda *_: crash.guarded(fn)())
            self.addAction(a)
        cur = lambda f: (lambda: f(self.current()) if self.current() else None)
        add("Ctrl+T", lambda: self.new_tab())
        add("Ctrl+N", lambda: self.app.open_window(None, False))
        add("Ctrl+Shift+N", lambda: self.app.open_window(None, True))
        add("Ctrl+W|Ctrl+F4", lambda: self.close_tab(self.current()))
        add("Ctrl+Shift+W", self.close)
        add("Ctrl+Shift+T", self.reopen_closed_tab)
        add("Ctrl+L|F6|Alt+D", self.focus_omnibox)
        add("Ctrl+K|Ctrl+E", lambda: (self.focus_omnibox(), self.omni.edit.setText("?"), self.omni.edit.setCursorPosition(1)))
        add("Ctrl+D", self.toggle_bookmark)
        add("Ctrl+Shift+B", lambda: self.app.settings.set("show_bookmarks_bar", not self.app.settings.get("show_bookmarks_bar")))
        add("Ctrl+H", lambda: self.open_url(f"{SCHEME}://history"))
        add("Ctrl+J", lambda: self.open_url(f"{SCHEME}://downloads"))
        add("Ctrl+Shift+O", lambda: self.open_url(f"{SCHEME}://bookmarks"))
        add("Ctrl+,", lambda: self.open_url(f"{SCHEME}://settings"))
        add("Ctrl+Shift+Del", lambda: self.open_url(f"{SCHEME}://history?clear=1"))
        add("Ctrl+F|F3", cur(lambda t: t.show_find()))
        add("Ctrl+G", cur(lambda t: t.find.search(t.find.edit.text(), True)))
        add("Ctrl+Shift+G", cur(lambda t: t.find.search(t.find.edit.text(), False)))
        add("Ctrl+P", cur(lambda t: t.print_page()))
        add("Ctrl+S", cur(lambda t: t.save_page()))
        add("Ctrl+U", cur(lambda t: t.view_source()))
        add("F12|Ctrl+Shift+I|Ctrl+Shift+J", cur(lambda t: t.toggle_devtools()))
        add("F5|Ctrl+R", cur(lambda t: t.reload()))
        add("Ctrl+F5|Ctrl+Shift+R|Shift+F5", cur(lambda t: t.reload(hard=True)))
        add("Esc", self._escape)
        add("Alt+Left", lambda: self.cur_do("back"))
        add("Alt+Right", lambda: self.cur_do("forward"))
        add("Alt+Home", self.go_home)
        add("Ctrl++|Ctrl+=|Ctrl+Shift+=", cur(lambda t: t.zoom_step(1)))
        add("Ctrl+-", cur(lambda t: t.zoom_step(-1)))
        add("Ctrl+0", cur(lambda t: t.set_zoom(self.app.settings.get("default_zoom") / 100)))
        add("F11", self.toggle_fullscreen)
        add("Ctrl+Tab|Ctrl+PgDown", lambda: self.cycle(1))
        add("Ctrl+Shift+Tab|Ctrl+PgUp", lambda: self.cycle(-1))
        add("Ctrl+Shift+A", self.tab_search_menu)
        add("Ctrl+Shift+M", lambda: self._toggle_mute_index(self.tabbar.currentIndex()))
        for n in range(1, 9):
            add(f"Ctrl+{n}|Alt+{n}", lambda n=n: self.tabbar.setCurrentIndex(min(n - 1, len(self.tabs) - 1)))
        add("Ctrl+9|Alt+9", lambda: self.tabbar.setCurrentIndex(len(self.tabs) - 1))

    def _escape(self):
        t = self.current()
        if self.omni.popup.isVisible():
            self.omni.popup.hide()
        elif t and t.find.isVisible():
            t.find.close_bar()
        elif t and t.loading:
            t.stop()

    def cycle(self, d):
        if self.tabs:
            self.tabbar.setCurrentIndex((self.tabbar.currentIndex() + d) % len(self.tabs))


    # ===================================================================== window chrome (maximise, resize edges)
    BORDER, CORNER = 4, 14


    def add_infobar(self, text, buttons=(), on_close=None):
        bar = InfoBar(text, list(buttons), on_close)
        self.infobars.addWidget(bar)
        return bar

    def toast(self, text):
        from PyQt6.QtWidgets import QToolTip
        QToolTip.showText(self.mapToGlobal(self.rect().center()), text, self)


    def _schedule_session(self):
        if not self.private:
            self._session_timer.start()

    def session_state(self):
        return {"private": self.private, "current": max(0, self.tabbar.currentIndex()),
                "tabs": [t.session_entry() for t in self.tabs if t.real_url().toString() and t.real_url().scheme() != "about"]}

    def closeEvent(self, ev):
        try:
            self.app.window_closing(self)
            for t in self.tabs:
                t.cleanup()
        except Exception:
            crash.log.exception("closeEvent")
        self.closedSignal.emit(self)
        super().closeEvent(ev)
