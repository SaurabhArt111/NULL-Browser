from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLineEdit, QPushButton, QTabWidget, QLabel, 
                             QToolBar, QStatusBar, QMenu, QDialog, QGridLayout,
                             QListWidget, QSplitter, QComboBox, QProgressBar,
                             QFrame, QFileDialog, QInputDialog, QWidgetAction, QFormLayout,
                             QCheckBox, QListWidgetItem, QMessageBox, QGraphicsOpacityEffect,
                             QToolButton)
from PyQt6.QtCore import (Qt, QUrl, QSize, pyqtSignal, QSettings, QTimer, QByteArray,
                          QPropertyAnimation, QEasingCurve, QEvent)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import (QWebEnginePage, QWebEngineProfile, QWebEngineDownloadRequest)
from PyQt6.QtGui import (QIcon, QAction, QKeySequence, QColor, QPixmap, QShortcut)
# Standard library imports
import os
import sys
import re
import traceback
import requests
import json
import datetime
import sqlite3
import math
import subprocess
import inspect

# Set up import path - modify to use a similar approach as main.py
current_dir = os.path.dirname(os.path.abspath(__file__))  # ui directory
parent_dir = os.path.dirname(current_dir)  # src directory
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

# Import project modules
from ui.managers.download_manager import DownloadManager
from ui.managers.bookmark_manager import BookmarkManager, BookmarksDialog
from ui.managers.history_manager import HistoryManager, HistoryDialog
from ui.managers.theme_manager import ThemeManager
from ui.dialogs.settings_dialog import SettingsDialog
from ui.components.browser_tab import BrowserTab, BrowserWebEnginePage
from ui.adblock import AdBlocker
from ui.newtab import build_new_tab_html, build_error_page


def safe_slot(func):
    """Decorator that swallows/reports exceptions raised inside Qt slots so a
    single bad callback (e.g. a flaky page load) can never crash the whole
    browser. Errors are surfaced in the status bar instead of a hard exit."""
    def wrapper(self, *args, **kwargs):
        try:
            signature = inspect.signature(func)
            signature.bind_partial(self, *args, **kwargs)
            return func(self, *args, **kwargs)
        except TypeError:
            try:
                return func(self)
            except Exception as exc:  # noqa: BLE001 - top level UI safety net
                traceback.print_exc()
                try:
                    self.statusBar().showMessage(f"Error: {exc}", 5000)
                except Exception:
                    pass
                return None
        except Exception as exc:  # noqa: BLE001 - top level UI safety net
            traceback.print_exc()
            try:
                self.statusBar().showMessage(f"Error: {exc}", 5000)
            except Exception:
                pass
            return None
    return wrapper


# Remove duplicate class that's already defined in browser_tab.py
# The BrowserWebEnginePage class is now imported from ui.components.browser_tab

# MainWindow class to represent the main application window
class MainWindow(QMainWindow):
    def __init__(self, private_mode=False):
        super().__init__()
        self.private_mode = private_mode
        title = "Null Browser" + (" (InPrivate)" if private_mode else "")
        self.setWindowTitle(title)
        self.setGeometry(100, 100, 1200, 800)
        self.setWindowIcon(QIcon.fromTheme("web-browser", QIcon()))

        self.settings = QSettings("NullBrowser", "Preferences")

        # Store downloads
        self.downloads = []
        # Stack of recently-closed tab URLs, for Ctrl+Shift+T "reopen closed tab"
        self.closed_tabs = []

        # InPrivate/incognito windows get their own off-the-record profile so
        # cookies, cache, and history never touch disk or the normal profile.
        if private_mode:
            self.web_profile = QWebEngineProfile(self)  # unnamed => off-the-record
            self.web_profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
            self.web_profile.setPersistentCookiesPolicy(
                QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
        else:
            self.web_profile = QWebEngineProfile.defaultProfile()

        # Connect to download request signal
        profile = self.web_profile
        profile.downloadRequested.connect(self.download_requested)

        # --- Ad / tracker blocker -------------------------------------
        self.adblocker = AdBlocker(self)
        self.adblocker.enabled = self.settings.value("adblock_enabled", True, type=bool)
        self.adblocker.blocked_count_changed.connect(self.update_shield_label)
        try:
            profile.setUrlRequestInterceptor(self.adblocker)
        except Exception:
            traceback.print_exc()

        self.block_popups = self.settings.value("block_popups", True, type=bool)

        # Initialize managers
        try:
            self.download_manager = DownloadManager(self)
            self.bookmark_manager = BookmarkManager(self)
            self.history_manager = HistoryManager(self)
        except Exception:
            traceback.print_exc()
            QMessageBox.warning(self, "Startup warning",
                                 "Some browser data (bookmarks/history/downloads) could "
                                 "not be loaded. Continuing with limited functionality.")
            self.download_manager = self.download_manager if hasattr(self, "download_manager") else DownloadManager(self)
            self.bookmark_manager = self.bookmark_manager if hasattr(self, "bookmark_manager") else BookmarkManager(self)
            self.history_manager = self.history_manager if hasattr(self, "history_manager") else HistoryManager(self)

        # Create central widget and layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Create toolbar
        self.create_toolbar()
        
        # Create bookmarks bar
        self.create_bookmarks_bar()
        
        # Create tab widget
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)  # drag-to-reorder tabs, like Chrome/Brave/Edge
        self.tabs.setDocumentMode(True)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self.current_tab_changed)

        # "+" corner button to open a new tab, mirroring Chrome's tab strip
        new_tab_corner_btn = QToolButton()
        new_tab_corner_btn.setText("+")
        new_tab_corner_btn.setToolTip("New tab (Ctrl+T)")
        new_tab_corner_btn.clicked.connect(lambda: self.add_new_tab())
        self.tabs.setCornerWidget(new_tab_corner_btn, Qt.Corner.TopRightCorner)

        # Middle-click on a tab closes it, matching every major browser
        self.tabs.tabBar().installEventFilter(self)
        
        layout.addWidget(self.tabs)
        
        # Set up status bar
        self.setup_status_bar()
        
        # Create first tab
        self.add_new_tab()
        
        # Set up menu bar
        self.create_menu_bar()
        
        # Create Downloads Menu
        self.create_downloads_menu()
        
        # Load settings
        self.load_settings()
        
        # Set up keyboard shortcuts
        self.setup_shortcuts()
        
        # Refresh bookmarks bar
        self.refresh_bookmarks_bar()

    def create_bookmarks_bar(self):
        # Create bookmarks toolbar - sits directly below the address bar,
        # like Chrome/Brave/Edge's bookmarks bar.
        self.bookmarks_toolbar = QToolBar("Bookmarks")
        self.bookmarks_toolbar.setObjectName("bookmarkBar")
        self.bookmarks_toolbar.setIconSize(QSize(14, 14))
        self.bookmarks_toolbar.setMovable(False)
        self.addToolBar(self.bookmarks_toolbar)
        
        # Add bookmark button
        add_bookmark_btn = QAction(QIcon.fromTheme("bookmark-new", QIcon()), "★ Bookmark this page", self)
        add_bookmark_btn.triggered.connect(self.add_bookmark)
        self.bookmarks_toolbar.addAction(add_bookmark_btn)
        
        # Add manage bookmarks button
        manage_bookmarks_btn = QAction(QIcon.fromTheme("bookmarks-organize", QIcon()), "All bookmarks", self)
        manage_bookmarks_btn.triggered.connect(self.show_bookmarks)
        self.bookmarks_toolbar.addAction(manage_bookmarks_btn)
        separator = self.bookmarks_toolbar.addSeparator()

        # Everything up to and including this separator is permanent chrome;
        # refresh_bookmarks_bar only ever touches actions added after it.
        self._bookmark_bar_base_actions = [add_bookmark_btn, manage_bookmarks_btn, separator]

    def refresh_bookmarks_bar(self):
        try:
            # Remove any bookmark entries added on a previous refresh, but
            # keep the permanent "add"/"manage" buttons and the separator.
            for action in list(self.bookmarks_toolbar.actions()):
                if action not in self._bookmark_bar_base_actions:
                    self.bookmarks_toolbar.removeAction(action)

            bookmarks = self.bookmark_manager.get_all_bookmarks()
            for bookmark_id, title, url, *_rest in bookmarks[:15]:
                display_title = title if len(title) <= 15 else title[:12] + "..."
                bookmark_action = QAction(display_title, self)
                bookmark_action.setToolTip(f"{title}\n{url}")
                bookmark_action.triggered.connect(lambda checked, u=url: self.navigate_to_bookmark(u))
                self.bookmarks_toolbar.addAction(bookmark_action)
        except Exception:
            traceback.print_exc()
            self.statusBar().showMessage("Could not refresh the bookmarks bar", 3000)
            
    @safe_slot
    def add_bookmark(self):
        current_tab = self.tabs.currentWidget()
        if current_tab is None:
            return
        url = current_tab.web_view.url().toString()
        title = current_tab.web_view.title() or url
        
        if url and url not in ("about:blank",) and not url.startswith("nullbrowser://"):
            self.bookmark_manager.add_bookmark(title, url)
            self.refresh_bookmarks_bar()
            self.statusBar().showMessage(f"Bookmarked: {title}", 2500)
        else:
            self.statusBar().showMessage("Nothing to bookmark on this page", 2500)
            
    def add_new_tab(self, url=None):
        try:
            tab = BrowserTab(self, profile=self.web_profile)
        except Exception:
            traceback.print_exc()
            self.statusBar().showMessage("Could not open a new tab", 4000)
            return None

        tab.url_changed.connect(lambda u: self.update_url_bar(u, tab))
        tab.title_changed.connect(lambda title: self.update_tab_title(title, tab))
        tab.loading_changed.connect(lambda loading: self.update_loading_status(loading, tab))
        tab.web_view.loadFinished.connect(lambda ok: self.handle_load_finished(ok, tab))
        try:
            tab.web_view.iconChanged.connect(lambda icon: self.update_tab_icon(icon, tab))
        except Exception:
            pass

        if url and url not in ("about:blank",):
            tab.web_view.setUrl(QUrl(url))
        else:
            self.load_new_tab_page(tab)

        index = self.tabs.addTab(tab, "New Tab")
        self.tabs.setCurrentIndex(index)
        self._animate_tab_switch()
        self.url_bar.setText("" if not url else tab.web_view.url().toString())
        self.url_bar.selectAll()
        self.url_bar.setFocus()
        
        return tab

    def load_new_tab_page(self, tab):
        """Loads the offline New Tab page (search box + bookmark tiles)."""
        try:
            bookmarks = self.bookmark_manager.get_all_bookmarks()
        except Exception:
            bookmarks = []
        theme = self.settings.value("theme", "Light")
        dark = str(theme).lower().startswith("dark")
        blocked = self.adblocker.total_blocked if hasattr(self, "adblocker") else 0
        html_content = build_new_tab_html(bookmarks=bookmarks, blocked_count=blocked, dark=dark)
        tab.web_view.setHtml(html_content, QUrl("nullbrowser://newtab/"))

    def handle_load_finished(self, ok, tab):
        """Shows a friendly error page instead of a blank/crashed tab."""
        try:
            if ok:
                return
            url = tab.web_view.url()
            scheme = url.scheme()
            # Don't show an error page for our own generated pages
            if scheme in ("data",) or url.toString().startswith("nullbrowser://"):
                return
            if url.toString() in ("", "about:blank"):
                return
            error_html = build_error_page(url.toString())
            tab.web_view.setHtml(error_html, url)
        except Exception:
            traceback.print_exc()

    def update_tab_icon(self, icon, tab):
        index = self.tabs.indexOf(tab)
        if index >= 0 and not icon.isNull():
            self.tabs.setTabIcon(index, icon)

    def _animate_tab_switch(self):
        """A subtle fade-in when a tab becomes active, to approximate the
        smooth transitions found in Chrome/Brave (Qt Widgets has no native
        CSS-style transitions, so we fake it with an opacity animation)."""
        try:
            current = self.tabs.currentWidget()
            if current is None:
                return
            effect = QGraphicsOpacityEffect(current)
            current.setGraphicsEffect(effect)
            anim = QPropertyAnimation(effect, b"opacity", current)
            anim.setDuration(160)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.finished.connect(lambda: current.setGraphicsEffect(None))
            anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
            self._tab_anim = anim  # keep a reference alive
        except Exception:
            pass
        
    def add_new_tab_with_web_view(self):
        # Create new tab with a web view and return the web view
        tab = self.add_new_tab()
        return tab.web_view

    # Method to load settings
    def create_downloads_menu(self):
        """
        Creates the Downloads (Ctrl+J) menu.
        """
        downloads_menu = self.menuBar().addMenu("Downloads")

        show_downloads_action = QAction("Show Downloads\tCtrl+J", self)
        show_downloads_action.triggered.connect(self.show_downloads)
        downloads_menu.addAction(show_downloads_action)
        
    @safe_slot
    def download_requested(self, download):
        """Handles file download requests: prompts for a save location (or
        uses the configured default download folder), then tracks progress
        through the DownloadManager dialog and the status bar."""
        suggested_filename = download.suggestedFileName() or "download"
        default_dir = self.settings.value("downloads_location", os.path.expanduser("~/Downloads"))
        try:
            os.makedirs(default_dir, exist_ok=True)
        except OSError:
            default_dir = os.path.expanduser("~")

        ask_every_time = self.settings.value("ask_download_location", True, type=bool)
        if ask_every_time:
            save_path, _ = QFileDialog.getSaveFileName(
                self, "Save File", os.path.join(default_dir, suggested_filename),
                "All Files (*)"
            )
            if not save_path:
                download.cancel()
                return
        else:
            save_path = os.path.join(default_dir, suggested_filename)

        try:
            download.setDownloadDirectory(os.path.dirname(save_path))
            download.setDownloadFileName(os.path.basename(save_path))
            download.accept()
        except Exception as e:
            self.statusBar().showMessage(f"Download failed to start: {e}", 4000)
            return

        self.downloads.append({"name": os.path.basename(save_path), "path": save_path, "status": "Downloading"})
        try:
            self.download_manager.add_download(download)
        except Exception:
            traceback.print_exc()

        self.statusBar().showMessage(f"Downloading {os.path.basename(save_path)}...", 3000)
        download.isFinishedChanged.connect(lambda: self.update_download_status(download, save_path))

    def update_download_status(self, download, save_path):
        """Updates status once a download finishes (success or failure)."""
        try:
            if download.isFinished():
                success = download.state() == QWebEngineDownloadRequest.DownloadState.DownloadCompleted
                for item in self.downloads:
                    if item["path"] == save_path:
                        item["status"] = "Completed" if success else "Failed"
                        break
                try:
                    self.download_manager.update_download_status(download)
                except Exception:
                    traceback.print_exc()
                msg = f"Downloaded {os.path.basename(save_path)}" if success else "Download failed"
                self.statusBar().showMessage(msg, 4000)
        except Exception:
            traceback.print_exc()

    def show_downloads(self):
        """Opens the full Downloads manager dialog."""
        try:
            self.download_manager.refresh_download_list()
            self.download_manager.show()
            self.download_manager.raise_()
            self.download_manager.activateWindow()
        except Exception as e:
            self.statusBar().showMessage(f"Could not open downloads: {e}", 4000)
        
    def create_toolbar(self):
        self.nav_toolbar = QToolBar("Navigation")
        self.nav_toolbar.setIconSize(QSize(16, 16))
        self.nav_toolbar.setMovable(False)
        self.addToolBar(self.nav_toolbar)
        
        # Back button
        back_btn = QAction(QIcon.fromTheme("go-previous", QIcon()), "Back", self)
        back_btn.setShortcut(QKeySequence("Alt+Left"))
        back_btn.triggered.connect(self.navigate_back)
        self.nav_toolbar.addAction(back_btn)
        
        # Forward button
        forward_btn = QAction(QIcon.fromTheme("go-next", QIcon()), "Forward", self)
        forward_btn.setShortcut(QKeySequence("Alt+Right"))
        forward_btn.triggered.connect(self.navigate_forward)
        self.nav_toolbar.addAction(forward_btn)
        
        # Reload button
        reload_btn = QAction(QIcon.fromTheme("view-refresh", QIcon()), "Reload", self)
        reload_btn.setShortcut(QKeySequence.StandardKey.Refresh)
        reload_btn.setShortcut(QKeySequence("Ctrl+R"))
        reload_btn.triggered.connect(self.reload_page)
        self.nav_toolbar.addAction(reload_btn)
        
        # Home button
        home_btn = QAction(QIcon.fromTheme("go-home", QIcon()), "Home", self)
        home_btn.triggered.connect(self.go_home)
        self.nav_toolbar.addAction(home_btn)
        
        self.nav_toolbar.addSeparator()

        # Security / privacy indicator (padlock) shown to the left of the URL
        self.security_label = QLabel("🔒")
        self.security_label.setToolTip("Connection is secure")
        self.security_label.setStyleSheet("padding: 0 4px;")
        self.nav_toolbar.addWidget(self.security_label)

        # URL bar
        self.url_bar = QLineEdit()
        self.url_bar.setPlaceholderText("Search Null Search or type a URL")
        self.url_bar.returnPressed.connect(self.navigate_to_url)
        self.nav_toolbar.addWidget(self.url_bar)

        # Ad-block "shield" button - shows how many trackers/ads were blocked
        # on the current site and lets the user view/disable blocking.
        self.shield_btn = QToolButton()
        self.shield_btn.setText("🛡")
        self.shield_btn.setToolTip("Privacy & ad-block: 0 blocked")
        self.shield_btn.clicked.connect(self.show_shield_menu)
        self.nav_toolbar.addWidget(self.shield_btn)
        
        # Search engines dropdown
        self.search_engine = QComboBox()
        self.search_engine.addItems(["Null Search", "Google", "Bing", "DuckDuckGo"])
        self.nav_toolbar.addWidget(self.search_engine)
        
        # Go button
        go_btn = QAction(QIcon.fromTheme("go-jump", QIcon()), "Go", self)
        go_btn.triggered.connect(self.navigate_to_url)
        self.nav_toolbar.addAction(go_btn)
        
        self.nav_toolbar.addSeparator()
        
        # Bookmarks button
        bookmarks_btn = QAction(QIcon.fromTheme("bookmarks", QIcon()), "Bookmarks", self)
        bookmarks_btn.triggered.connect(self.show_bookmarks)
        self.nav_toolbar.addAction(bookmarks_btn)

        # Downloads button
        downloads_btn = QAction(QIcon.fromTheme("emblem-downloads", QIcon()), "Downloads", self)
        downloads_btn.triggered.connect(self.show_downloads)
        self.nav_toolbar.addAction(downloads_btn)
        
        # Menu button
        menu_btn = QAction(QIcon.fromTheme("application-menu", QIcon()), "Menu", self)
        menu_btn.triggered.connect(self.show_menu)
        self.nav_toolbar.addAction(menu_btn)
        
        # New tab button
        new_tab_btn = QAction(QIcon.fromTheme("tab-new", QIcon()), "New Tab", self)
        new_tab_btn.triggered.connect(self.add_new_tab)
        self.nav_toolbar.addAction(new_tab_btn)

    @safe_slot
    def update_shield_label(self, count):
        self.shield_btn.setToolTip(f"Privacy & ad-block: {count} blocked on this session")
        self.shield_btn.setText(f"🛡{count}" if count else "🛡")

    @safe_slot
    def show_shield_menu(self):
        menu = QMenu(self)
        toggle_action = QAction(
            "Disable ad-block" if self.adblocker.enabled else "Enable ad-block", self)
        toggle_action.triggered.connect(self.toggle_adblock)
        menu.addAction(toggle_action)

        current_tab = self.tabs.currentWidget()
        if current_tab is not None:
            host = current_tab.web_view.url().host()
            if host:
                allow_action = QAction(
                    f"Allow ads on {host}" if not self.adblocker.is_site_allowed(host)
                    else f"Block ads on {host} again", self)
                allow_action.triggered.connect(lambda: self.toggle_site_allowed(host))
                menu.addAction(allow_action)

        menu.addSeparator()
        recent = self.adblocker.recent_blocked(10)
        if recent:
            menu.addAction(QAction("Recently blocked:", self)).setEnabled(False)
            for url in recent:
                short = url if len(url) < 60 else url[:57] + "..."
                a = QAction("  " + short, self)
                a.setEnabled(False)
                menu.addAction(a)
        else:
            no_action = QAction("Nothing blocked yet on this page", self)
            no_action.setEnabled(False)
            menu.addAction(no_action)

        menu.exec(self.shield_btn.mapToGlobal(self.shield_btn.rect().bottomLeft()))

    def toggle_adblock(self):
        self.adblocker.enabled = not self.adblocker.enabled
        self.settings.setValue("adblock_enabled", self.adblocker.enabled)
        state = "enabled" if self.adblocker.enabled else "disabled"
        self.statusBar().showMessage(f"Ad-block {state}", 3000)

    def toggle_site_allowed(self, host):
        allowed = not self.adblocker.is_site_allowed(host)
        self.adblocker.set_site_allowed(host, allowed)
        msg = f"Ads allowed on {host}" if allowed else f"Ads blocked again on {host}"
        self.statusBar().showMessage(msg, 3000)
        current_tab = self.tabs.currentWidget()
        if current_tab is not None:
            current_tab.web_view.reload()
        
    def setup_status_bar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        # Add progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(120)
        self.progress_bar.setMaximumHeight(12)
        self.progress_bar.setVisible(False)
        self.status_bar.addPermanentWidget(self.progress_bar)
        
        # Add zoom label
        self.zoom_label = QLabel("100%")
        self.status_bar.addPermanentWidget(self.zoom_label)
        
    def create_menu_bar(self):
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("&File")
        
        new_tab_action = QAction("&New Tab", self)
        new_tab_action.setShortcut(QKeySequence.StandardKey.AddTab)
        new_tab_action.triggered.connect(self.add_new_tab)
        file_menu.addAction(new_tab_action)
        
        new_window_action = QAction("New &Window", self)
        new_window_action.setShortcut(QKeySequence.StandardKey.New)
        new_window_action.triggered.connect(self.new_window)
        file_menu.addAction(new_window_action)
        
        file_menu.addSeparator()
        
        save_page_action = QAction("&Save Page", self)
        save_page_action.setShortcut(QKeySequence.StandardKey.Save)
        save_page_action.triggered.connect(self.save_page)
        file_menu.addAction(save_page_action)
        
        print_action = QAction("&Print...", self)
        print_action.setShortcut(QKeySequence.StandardKey.Print)
        print_action.triggered.connect(self.print_page)
        file_menu.addAction(print_action)
        
        file_menu.addSeparator()
        
        private_window_action = QAction("New &Private Window", self)
        private_window_action.triggered.connect(self.new_private_window)
        file_menu.addAction(private_window_action)
        
        file_menu.addSeparator()
        
        close_tab_action = QAction("&Close Tab", self)
        close_tab_action.setShortcut(QKeySequence.StandardKey.Close)
        close_tab_action.setShortcut(QKeySequence("Ctrl+W"))


        close_tab_action.triggered.connect(lambda: self.close_tab(self.tabs.currentIndex()))
        file_menu.addAction(close_tab_action)
        
        exit_action = QAction("E&xit", self)
        exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Edit menu
        edit_menu = menubar.addMenu("&Edit")
        
        find_action = QAction("&Find...", self)
        find_action.setShortcut(QKeySequence.StandardKey.Find)
        find_action.triggered.connect(self.find_in_page)
        edit_menu.addAction(find_action)
        
        # View menu
        view_menu = menubar.addMenu("&View")
        
        zoom_in_action = QAction("Zoom &In", self)
        zoom_in_action.setShortcut(QKeySequence.StandardKey.ZoomIn)
        zoom_in_action.triggered.connect(self.zoom_in)
        view_menu.addAction(zoom_in_action)
        
        zoom_out_action = QAction("Zoom &Out", self)
        zoom_out_action.setShortcut(QKeySequence.StandardKey.ZoomOut)
        zoom_out_action.triggered.connect(self.zoom_out)
        view_menu.addAction(zoom_out_action)
        
        zoom_reset_action = QAction("&Reset Zoom", self)
        zoom_reset_action.triggered.connect(self.zoom_reset)
        view_menu.addAction(zoom_reset_action)
        
        view_menu.addSeparator()
        
        fullscreen_action = QAction("&Full Screen", self)
        fullscreen_action.setShortcut(Qt.Key.Key_F11)
        fullscreen_action.setCheckable(True)
        fullscreen_action.triggered.connect(self.toggle_fullscreen)
        view_menu.addAction(fullscreen_action)
        
        # History menu
        history_menu = menubar.addMenu("&History")
        
        # Back/Forward already have Alt+Left / Alt+Right bound on the toolbar
        # buttons; we intentionally don't set a second shortcut here to avoid
        # Qt treating the key sequence as ambiguous.
        back_action = QAction("&Back\tAlt+Left", self)
        back_action.triggered.connect(self.navigate_back)
        history_menu.addAction(back_action)
        
        forward_action = QAction("&Forward\tAlt+Right", self)
        forward_action.triggered.connect(self.navigate_forward)
        history_menu.addAction(forward_action)
        
        history_menu.addSeparator()
        
        show_history_action = QAction("Show &History", self)
        show_history_action.setShortcut(QKeySequence("Ctrl+H"))
        show_history_action.triggered.connect(self.show_history)
        history_menu.addAction(show_history_action)
        
        # Bookmarks menu
        bookmarks_menu = menubar.addMenu("&Bookmarks")
        
        add_bookmark_action = QAction("&Add Bookmark", self)
        add_bookmark_action.setShortcut(QKeySequence("Ctrl+D"))
        add_bookmark_action.triggered.connect(self.add_bookmark)
        bookmarks_menu.addAction(add_bookmark_action)
        
        show_bookmarks_action = QAction("&Show Bookmarks", self)
        show_bookmarks_action.setShortcut(QKeySequence("Ctrl+B"))
        show_bookmarks_action.triggered.connect(self.show_bookmarks)
        bookmarks_menu.addAction(show_bookmarks_action)
        
        # Tools menu
        tools_menu = menubar.addMenu("&Tools")
        
        dev_tools_action = QAction("&Developer Tools", self)
        dev_tools_action.setShortcut(QKeySequence("Ctrl+Shift+I"))
        dev_tools_action.triggered.connect(self.toggle_developer_tools)
        tools_menu.addAction(dev_tools_action)
        
        view_source_action = QAction("&View Page Source", self)
        view_source_action.triggered.connect(self.view_page_source)
        tools_menu.addAction(view_source_action)
        
        tools_menu.addSeparator()
                
        settings_action = QAction("Settings", self)
        settings_action.triggered.connect(self.open_settings)
        tools_menu.addAction(settings_action)
        
        # Help menu
        help_menu = menubar.addMenu("&Help")
        
        about_action = QAction("&About Null Browser", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
        
    def setup_shortcuts(self):
        # Tab-by-number shortcuts (Alt+1..Alt+9), like Chrome/Brave/Edge
        for i in range(1, 10):
            shortcut = QShortcut(QKeySequence(f"Alt+{i}"), self)
            shortcut.activated.connect(lambda idx=i-1: self.activate_tab(idx))

        def add_shortcut(seq, slot):
            s = QShortcut(QKeySequence(seq), self)
            s.activated.connect(slot)
            return s

        # NOTE: shortcuts already registered on a QAction elsewhere (menu bar
        # or toolbar) - e.g. Ctrl+T, Ctrl+W, Ctrl+N, Ctrl+D, Ctrl+H, Ctrl+F,
        # Ctrl+R, Ctrl+S, Ctrl+P, zoom in/out, Alt+Left/Right, Ctrl+Shift+I -
        # are intentionally NOT duplicated here, since two bindings for the
        # same key sequence make Qt treat both as ambiguous and neither fires.
        add_shortcut("Ctrl+Shift+T", self.reopen_closed_tab)
        add_shortcut("Ctrl+L", self.focus_url_bar)
        add_shortcut("F6", self.focus_url_bar)
        add_shortcut("Alt+D", self.focus_url_bar)
        add_shortcut("Ctrl+Shift+N", self.new_private_window)
        add_shortcut("Ctrl+Shift+B", self.show_bookmarks)
        add_shortcut("Ctrl+J", self.show_downloads)
        add_shortcut("Ctrl+Shift+Delete", self.open_clear_browsing_data)
        add_shortcut("F5", self.reload_page)
        add_shortcut("Ctrl+0", self.zoom_reset)
        add_shortcut("Ctrl+Tab", self.next_tab)
        add_shortcut("Ctrl+PgDown", self.next_tab)
        add_shortcut("Ctrl+Shift+Tab", self.previous_tab)
        add_shortcut("Ctrl+PgUp", self.previous_tab)

    def focus_url_bar(self):
        self.url_bar.setFocus()
        self.url_bar.selectAll()

    def next_tab(self):
        if self.tabs.count() > 1:
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + 1) % self.tabs.count())

    def previous_tab(self):
        if self.tabs.count() > 1:
            self.tabs.setCurrentIndex((self.tabs.currentIndex() - 1) % self.tabs.count())

    def open_clear_browsing_data(self):
        dialog = SettingsDialog(self)
        try:
            dialog.show_privacy_tab()
        except Exception:
            pass
        dialog.exec()

    def activate_tab(self, index):
        if index < self.tabs.count():
            self.tabs.setCurrentIndex(index)
            
    def eventFilter(self, obj, event):
        try:
            if obj is self.tabs.tabBar() and event.type() == QEvent.Type.MouseButtonRelease:
                if event.button() == Qt.MouseButton.MiddleButton:
                    index = self.tabs.tabBar().tabAt(event.pos())
                    if index >= 0:
                        self.close_tab(index)
                        return True
        except Exception:
            pass
        return super().eventFilter(obj, event)

    def close_tab(self, index):
        try:
            widget = self.tabs.widget(index)
            if widget is not None:
                url = widget.web_view.url().toString()
                if url and url not in ("about:blank",):
                    self.closed_tabs.append(url)
                    if len(self.closed_tabs) > 25:
                        self.closed_tabs.pop(0)
        except Exception:
            pass

        if self.tabs.count() > 1:
            self.tabs.removeTab(index)
        else:
            self.add_new_tab()
            self.tabs.removeTab(index)

    def reopen_closed_tab(self):
        if self.closed_tabs:
            url = self.closed_tabs.pop()
            self.add_new_tab(url)
            self.statusBar().showMessage("Reopened closed tab", 2000)
        else:
            self.statusBar().showMessage("No recently closed tabs", 2000)
            
    def current_tab_changed(self, index):
        if index >= 0:
            tab = self.tabs.widget(index)
            url = tab.web_view.url().toString()
            self.url_bar.setText("" if url.startswith("nullbrowser://") else url)
            self.update_zoom_label(tab.web_view.zoomFactor())
            self.update_security_indicator(url)
            self._animate_tab_switch()

    def update_security_indicator(self, url):
        """Reflects connection security in a small padlock next to the URL bar,
        similar to Chrome/Brave/Edge's site security chip."""
        try:
            scheme = QUrl(url).scheme()
            if scheme == "https":
                self.security_label.setText("🔒")
                self.security_label.setToolTip("Connection is secure (HTTPS)")
            elif scheme == "http":
                self.security_label.setText("⚠️")
                self.security_label.setToolTip("Not secure - this site uses plain HTTP")
            elif scheme in ("file", "nullbrowser", ""):
                self.security_label.setText("📄")
                self.security_label.setToolTip("Local page")
            else:
                self.security_label.setText("ℹ️")
                self.security_label.setToolTip(f"Scheme: {scheme}")
        except Exception:
            self.security_label.setText("ℹ️")

    def update_url_bar(self, url, tab=None):
        if tab == self.tabs.currentWidget():
            self.url_bar.setText("" if url.startswith("nullbrowser://") else url)
            self.url_bar.setCursorPosition(0)
            self.update_security_indicator(url)
            
            # Add to history (skip private browsing and internal pages)
            try:
                title = tab.web_view.title()
                if title and url and url != "about:blank" and not url.startswith("nullbrowser://") \
                        and not self.private_mode:
                    self.history_manager.add_visit(title, url)
            except Exception:
                traceback.print_exc()
            
    def update_tab_title(self, title, tab=None):
        if not title:
            title = "New Tab"
            
        index = self.tabs.indexOf(tab)
        if index >= 0:
            # Truncate long titles
            if len(title) > 20:
                title = title[:17] + "..."
                
            self.tabs.setTabText(index, title)
            
    def update_loading_status(self, loading, tab=None):
        if tab == self.tabs.currentWidget():
            if loading:
                # Indeterminate ("busy") progress bar - real load progress isn't
                # exposed per-request, and a fake synchronous loop would freeze
                # the whole UI thread, so we animate a marquee instead.
                self.progress_bar.setRange(0, 0)
                self.progress_bar.setVisible(True)
            else:
                self.progress_bar.setRange(0, 100)
                self.progress_bar.setValue(100)
                self.progress_bar.setVisible(False)
        # Reflect loading state as a spinner-ish tab title suffix
        try:
            index = self.tabs.indexOf(tab)
            if index >= 0:
                self.tabs.setTabToolTip(index, "Loading..." if loading else tab.web_view.url().toString())
        except Exception:
            pass
                
    def update_zoom_label(self, factor):
        zoom_percent = int(factor * 100)
        self.zoom_label.setText(f"{zoom_percent}%")
            
    def _looks_like_url(self, text):
        """Best-effort heuristic (à la Chrome's omnibox) to decide whether the
        typed text is a navigable address or a search query."""
        text = text.strip()
        if not text:
            return False
        if text.startswith(('http://', 'https://', 'file://', 'about:', 'nullbrowser://')):
            return True
        if ' ' in text:
            return False
        if text.startswith('localhost') or re.match(r'^\d{1,3}(\.\d{1,3}){3}(:\d+)?$', text):
            return True
        # domain.tld or domain.tld/path, no spaces, has a dot and no illegal chars
        return bool(re.match(r'^[\w-]+(\.[\w-]+)+(:\d+)?(/.*)?$', text))

    @safe_slot
    def navigate_to_url(self):
        current_tab = self.tabs.currentWidget()
        if current_tab is None:
            return
        text = self.url_bar.text().strip()
        if not text:
            return

        if not self._looks_like_url(text):
            self.perform_search()
            return

        url = text
        if not url.startswith(('http://', 'https://', 'file://', 'about:', 'nullbrowser://')):
            url = 'https://' + url

        try:
            current_tab.web_view.setUrl(QUrl(url))
        except Exception as e:
            self.statusBar().showMessage(f"Could not navigate: {e}", 4000)

    @safe_slot
    def navigate_back(self):
        current_tab = self.tabs.currentWidget()
        if current_tab:
            current_tab.web_view.back()

    @safe_slot
    def navigate_forward(self):
        current_tab = self.tabs.currentWidget()
        if current_tab:
            current_tab.web_view.forward()

    @safe_slot
    def reload_page(self):
        current_tab = self.tabs.currentWidget()
        if current_tab:
            current_tab.web_view.reload()

    @safe_slot
    def go_home(self):
        current_tab = self.tabs.currentWidget()
        if not current_tab:
            return
        home_page = self.settings.value("home_page", "newtab")
        if not home_page or home_page == "newtab":
            self.load_new_tab_page(current_tab)
        else:
            current_tab.web_view.setUrl(QUrl(home_page))

    @safe_slot
    def perform_search(self):
        query = self.url_bar.text().strip()
        if not query:
            return
        current_tab = self.tabs.currentWidget()
        if current_tab is None:
            return
        search_engine = self.search_engine.currentText()
        from urllib.parse import quote_plus
        encoded_query = quote_plus(query)

        if search_engine == "Null Search":
            # Query the local Null Search Engine's JSON API. Falls back
            # gracefully (with a clear status-bar message) if the local
            # search server isn't running.
            try:
                response = requests.get(
                    "http://localhost:8000/api/search",
                    params={"q": query, "limit": 20},
                    timeout=4
                )
                response.raise_for_status()
                results = response.json().get("results", [])
                if results:
                    self.display_search_results(query, results)
                else:
                    self.display_no_results(query)
            except requests.exceptions.ConnectionError:
                self.statusBar().showMessage(
                    "Null Search Engine isn't running on localhost:8000 - "
                    "start it, or switch to Google/Bing/DuckDuckGo.", 6000)
                self.display_no_results(query, offline=True)
            except Exception as e:
                self.statusBar().showMessage(f"Search error: {e}", 5000)
                self.display_no_results(query, offline=True)
        elif search_engine == "Google":
            current_tab.web_view.setUrl(QUrl(f"https://www.google.com/search?q={encoded_query}"))
        elif search_engine == "Bing":
            current_tab.web_view.setUrl(QUrl(f"https://www.bing.com/search?q={encoded_query}"))
        elif search_engine == "DuckDuckGo":
            current_tab.web_view.setUrl(QUrl(f"https://duckduckgo.com/?q={encoded_query}"))
            
    def display_search_results(self, query, results):
        """Display search results in a nicely formatted tab"""
        import html as html_lib
        query = html_lib.escape(query)
        # Create a new tab for results
        results_tab = BrowserTab(self, profile=self.web_profile)
        
        # Create the HTML content
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Search Results for "{query}"</title>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    margin: 0;
                    padding: 20px;
                    background-color: #f8f9fa;
                }}
                .search-box {{
                    background-color: #fff;
                    border-radius: 8px;
                    padding: 15px;
                    margin-bottom: 20px;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                }}
                .search-box input {{
                    width: 80%;
                    padding: 10px;
                    border: 1px solid #dfe1e5;
                    border-radius: 24px;
                    font-size: 16px;
                    outline: none;
                }}
                .search-box button {{
                    padding: 10px 20px;
                    background-color: #4285f4;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    cursor: pointer;
                    margin-left: 10px;
                }}
                .result {{
                    background-color: #fff;
                    border-radius: 8px;
                    padding: 15px;
                    margin-bottom: 15px;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                }}
                .result h2 {{
                    margin-top: 0;
                    margin-bottom: 5px;
                }}
                .result h2 a {{
                    color: #1a0dab;
                    text-decoration: none;
                }}
                .result h2 a:hover {{
                    text-decoration: underline;
                }}
                .result .url {{
                    color: #006621;
                    font-size: 14px;
                    margin-bottom: 8px;
                }}
                .result .snippet {{
                    color: #4d5156;
                    line-height: 1.58;
                }}
                .results-count {{
                    color: #70757a;
                    font-size: 14px;
                    margin-bottom: 20px;
                }}
            </style>
        </head>
        <body>
            <div class="search-box">
                <form action="http://localhost:8000/search" method="get">
                    <input type="text" name="q" value="{query}" placeholder="Search...">
                    <button type="submit">Search</button>
                </form>
            </div>
            
            <div class="results-count">
                About {len(results)} results
            </div>
        """
        
        # Add each result to the HTML (escaped to avoid injecting markup
        # from untrusted crawled content into the results page)
        for result in results:
            r_url = html_lib.escape(str(result.get('url', '')))
            r_title = html_lib.escape(str(result.get('title', 'Untitled')))
            r_snippet = html_lib.escape(str(result.get('content', result.get('description', ''))))[:220]
            html_content += f"""
            <div class="result">
                <h2><a href="{r_url}">{r_title}</a></h2>
                <div class="url">{r_url}</div>
                <div class="snippet">{r_snippet}...</div>
            </div>
            """
        
        # Close the HTML
        html_content += """
        </body>
        </html>
        """
        
        # Set the HTML content
        results_tab.web_view.setHtml(html_content, QUrl("http://localhost:8000/"))
        
        # Add the tab
        tab_index = self.tabs.addTab(results_tab, f"Results: {query}")
        self.tabs.setCurrentIndex(tab_index)
        
    def display_no_results(self, query, offline=False):
        """Display a message when no results are found (or the local search
        server is unreachable, indicated by offline=True)."""
        import html as html_lib
        query = html_lib.escape(query)
        # Create a new tab
        results_tab = BrowserTab(self, profile=self.web_profile)
        offline_notice = (
            '<p style="color:#c5221f;">The Null Search Engine server does not '
            'appear to be running on <code>localhost:8000</code>. Start it, or '
            'pick Google / Bing / DuckDuckGo from the search-engine dropdown.</p>'
        ) if offline else ""
        
        # Create HTML content
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>No Results Found</title>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    margin: 0;
                    padding: 20px;
                    background-color: #f8f9fa;
                    text-align: center;
                }}
                .search-box {{
                    background-color: #fff;
                    border-radius: 8px;
                    padding: 15px;
                    margin-bottom: 20px;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                }}
                .search-box input {{
                    width: 80%;
                    padding: 10px;
                    border: 1px solid #dfe1e5;
                    border-radius: 24px;
                    font-size: 16px;
                    outline: none;
                }}
                .search-box button {{
                    padding: 10px 20px;
                    background-color: #4285f4;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    cursor: pointer;
                    margin-left: 10px;
                }}
                .no-results {{
                    background-color: #fff;
                    border-radius: 8px;
                    padding: 30px;
                    margin-top: 50px;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                    text-align: center;
                }}
                .no-results h2 {{
                    color: #5f6368;
                }}
                .suggestions {{
                    margin-top: 20px;
                    text-align: left;
                    display: inline-block;
                }}
            </style>
        </head>
        <body>
            <div class="search-box">
                <form action="http://localhost:8000/search" method="get">
                    <input type="text" name="q" value="{query}" placeholder="Search...">
                    <button type="submit">Search</button>
                </form>
            </div>
            
            <div class="no-results">
                <h2>No results found for "{query}"</h2>
                {offline_notice}
                <div class="suggestions">
                    <p>Suggestions:</p>
                    <ul>
                        <li>Check your spelling</li>
                        <li>Try more general keywords</li>
                        <li>Try different keywords</li>
                        <li>Try fewer keywords</li>
                    </ul>
                </div>
            </div>
        </body>
        </html>
        """
        
        # Set the HTML content
        results_tab.web_view.setHtml(html_content, QUrl("http://localhost:8000/"))
        
        # Add the tab
        tab_index = self.tabs.addTab(results_tab, f"No Results: {query}")
        self.tabs.setCurrentIndex(tab_index)
        
    def show_bookmarks(self):
        dialog = BookmarksDialog(self.bookmark_manager, self)
        dialog.bookmark_selected.connect(self.navigate_to_bookmark)
        dialog.exec()
        
    def navigate_to_bookmark(self, url):
        current_tab = self.tabs.currentWidget()
        current_tab.web_view.setUrl(QUrl(url))
        
    def show_history(self):
        dialog = HistoryDialog(self.history_manager, self)
        dialog.url_selected.connect(self.navigate_to_history_item)
        dialog.exec()
        
    def navigate_to_history_item(self, url):
        current_tab = self.tabs.currentWidget()
        current_tab.web_view.setUrl(QUrl(url))
        
    def clear_history(self):
        self.history_manager.clear_history()
        
    def find_in_page(self):
        current_tab = self.tabs.currentWidget()
        current_tab.toggle_find()
        
    def zoom_in(self):
        current_tab = self.tabs.currentWidget()
        current_tab.zoom_in()
        self.update_zoom_label(current_tab.web_view.zoomFactor())
        
    def zoom_out(self):
        current_tab = self.tabs.currentWidget()
        current_tab.zoom_out()
        self.update_zoom_label(current_tab.web_view.zoomFactor())
        
    def zoom_reset(self):
        current_tab = self.tabs.currentWidget()
        current_tab.reset_zoom()
        self.update_zoom_label(current_tab.web_view.zoomFactor())
        
    def toggle_fullscreen(self, checked):
        if checked:
            self.showFullScreen()
        else:
            self.showNormal()
            
    def _launch_new_instance(self, extra_args=None):
        import subprocess
        current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        main_script = os.path.join(current_dir, "main.py")
        if not os.path.exists(main_script):
            self.statusBar().showMessage("Could not locate main.py to launch a new window", 4000)
            return
        try:
            subprocess.Popen([sys.executable, main_script] + (extra_args or []))
        except OSError as e:
            self.statusBar().showMessage(f"Could not open new window: {e}", 4000)

    def new_window(self):
        self._launch_new_instance()

    def new_private_window(self):
        self._launch_new_instance(["--private"])
        
    @safe_slot
    def save_page(self):
        current_tab = self.tabs.currentWidget()
        if current_tab is None:
            return

        file_dialog = QFileDialog(self)
        file_dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        file_dialog.setNameFilter("HTML Files (*.html);;All Files (*)")

        if file_dialog.exec():
            file_path = file_dialog.selectedFiles()[0]
            try:
                current_tab.web_view.page().save(
                    file_path, QWebEngineDownloadRequest.SavePageFormat.CompleteHtmlSaveFormat)
                self.statusBar().showMessage(f"Page saved to: {file_path}", 3000)
            except Exception as e:
                self.statusBar().showMessage(f"Could not save page: {e}", 4000)

    @safe_slot
    def print_page(self):
        current_tab = self.tabs.currentWidget()
        if not current_tab:
            return
        page = current_tab.web_view.page()

        file_dialog = QFileDialog(self)
        file_dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        file_dialog.setNameFilter("PDF Files (*.pdf)")
        file_dialog.selectFile("page.pdf")
        if not file_dialog.exec():
            return
        file_path = file_dialog.selectedFiles()[0]
        if not file_path.lower().endswith(".pdf"):
            file_path += ".pdf"

        def save_pdf_callback(pdf_data):
            try:
                if pdf_data:
                    with open(file_path, "wb") as f:
                        f.write(pdf_data)
                    self.statusBar().showMessage(f"Saved PDF to {file_path}", 4000)
                else:
                    self.statusBar().showMessage("Print to PDF failed", 4000)
            except OSError as e:
                self.statusBar().showMessage(f"Could not write PDF: {e}", 4000)

        try:
            page.printToPdf(save_pdf_callback)
        except Exception as e:
            self.statusBar().showMessage(f"Print failed: {e}", 4000)

    def toggle_developer_tools(self):
        """Opens Chromium's built-in DevTools in a separate inspector window,
        mirroring Chrome/Brave/Edge's Ctrl+Shift+I behavior."""
        current_tab = self.tabs.currentWidget()
        if not current_tab:
            return
        try:
            if not hasattr(self, "_devtools_windows"):
                self._devtools_windows = []
            inspector_view = QWebEngineView()
            inspector_view.setWindowTitle("Developer Tools")
            inspector_view.resize(1000, 700)
            current_tab.web_view.page().setDevToolsPage(inspector_view.page())
            inspector_view.show()
            self._devtools_windows.append(inspector_view)
        except Exception as e:
            self.statusBar().showMessage(f"Developer tools unavailable: {e}", 4000)
        
    @safe_slot
    def view_page_source(self):
        current_tab = self.tabs.currentWidget()
        if current_tab is None:
            return
        url = current_tab.web_view.url().toString()

        import html as html_lib

        def show_source(raw_html):
            source_tab = BrowserTab(self, profile=self.web_profile)
            escaped = html_lib.escape(raw_html or "(empty document)")
            content = (
                f"<html><head><title>Source of {html_lib.escape(url)}</title>"
                "<style>body{font-family:monospace;white-space:pre-wrap;"
                "word-break:break-all;padding:12px;} </style></head>"
                f"<body>{escaped}</body></html>"
            )
            source_tab.web_view.page().setHtml(content)
            index = self.tabs.addTab(source_tab, "View Source")
            self.tabs.setCurrentIndex(index)

        try:
            current_tab.web_view.page().toHtml(show_source)
        except Exception as e:
            self.statusBar().showMessage(f"Could not read page source: {e}", 4000)
        
    def show_settings(self):
        # Use the open_settings method for consistency
        self.open_settings()
        
    @safe_slot
    def show_about(self):
        about_text = f"""
        <html><head><style>
          body {{ font-family: -apple-system, "Segoe UI", Arial, sans-serif; padding: 32px; max-width: 640px; }}
          h1 {{ margin-bottom: 4px; }}
          .ver {{ color: #5f6368; margin-bottom: 24px; }}
          ul {{ line-height: 1.9; }}
        </style></head><body>
        <h1>Null Browser</h1>
        <div class="ver">Version 2.1 &middot; built on PyQt6 / QtWebEngine (Chromium)</div>
        <p>A privacy-focused browser with a built-in ad &amp; tracker blocker,
        bookmarks, history, downloads, multiple themes, and InPrivate browsing.</p>
        <ul>
          <li>Ad-block status: <b>{"On" if self.adblocker.enabled else "Off"}</b>
              ({self.adblocker.total_blocked} blocked this session)</li>
          <li>Popup blocker: <b>{"On" if self.block_popups else "Off"}</b></li>
          <li>Tabs open: <b>{self.tabs.count()}</b></li>
          <li>Bookmarks: <b>{len(self.bookmark_manager.get_all_bookmarks())}</b></li>
        </ul>
        <p>&copy; 2025-2026 Null Browser Team</p>
        </body></html>
        """

        about_tab = BrowserTab(self, profile=self.web_profile)
        about_tab.web_view.setHtml(about_text, QUrl("nullbrowser://about/"))

        index = self.tabs.addTab(about_tab, "About Null Browser")
        self.tabs.setCurrentIndex(index)
        
    def show_menu(self):
        menu = QMenu(self)
        
        new_tab_action = menu.addAction("New Tab")
        new_tab_action.triggered.connect(self.add_new_tab)
        
        new_window_action = menu.addAction("New Window")
        new_window_action.triggered.connect(self.new_window)
        
        menu.addSeparator()
        
        bookmarks_action = menu.addAction("Bookmarks")
        bookmarks_action.triggered.connect(self.show_bookmarks)
        
        history_action = menu.addAction("History")
        history_action.triggered.connect(self.show_history)
        
        menu.addSeparator()
        
        settings_action = menu.addAction("Settings")
        settings_action.triggered.connect(self.open_settings)
        
        # Position the menu
        menu.exec(self.nav_toolbar.mapToGlobal(self.nav_toolbar.rect().bottomRight()))

    def open_settings(self):
        dialog = SettingsDialog(self)
        dialog.exec()

    def load_settings(self):
        try:
            settings = QSettings("NullBrowser", "Preferences")

            # Load window geometry
            geometry = settings.value("geometry")
            if geometry:
                self.restoreGeometry(geometry)

            # Load search engine preference
            search_engine = settings.value("search_engine", 0)
            try:
                idx = int(search_engine)
            except (TypeError, ValueError):
                idx = 0
            if 0 <= idx < self.search_engine.count():
                self.search_engine.setCurrentIndex(idx)

            self.adblocker.enabled = settings.value("adblock_enabled", True, type=bool)
            self.block_popups = settings.value("block_popups", True, type=bool)
        except Exception:
            traceback.print_exc()
            self.statusBar().showMessage("Could not load saved settings, using defaults", 4000)

    def save_settings(self):
        try:
            settings = QSettings("NullBrowser", "Preferences")

            # Save window geometry
            settings.setValue("geometry", self.saveGeometry())

            # Save search engine preference
            settings.setValue("search_engine", self.search_engine.currentIndex())
            settings.setValue("adblock_enabled", self.adblocker.enabled)
            settings.setValue("block_popups", self.block_popups)

            self.statusBar().showMessage("Settings saved", 3000)
        except Exception as e:
            traceback.print_exc()
            self.statusBar().showMessage(f"Could not save settings: {e}", 4000)

    def clear_browsing_data(self, cache=True, cookies=True, history=True):
        """Clears cache/cookies/history - the 'Clear browsing data' action
        found in Chrome/Brave/Edge (Ctrl+Shift+Delete)."""
        try:
            profile = QWebEngineProfile.defaultProfile()
            if cache:
                profile.clearHttpCache()
            if cookies:
                profile.cookieStore().deleteAllCookies()
            if history:
                self.history_manager.clear_history()
            self.statusBar().showMessage("Browsing data cleared", 3000)
        except Exception as e:
            traceback.print_exc()
            self.statusBar().showMessage(f"Could not clear browsing data: {e}", 4000)

    def closeEvent(self, event):
        try:
            self.save_settings()
        except Exception:
            traceback.print_exc()
        super().closeEvent(event)
        

class SearchResultsWidget(QWidget):
    def __init__(self, results, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        
        # Add title
        title = QLabel("Search Results")
        title.setStyleSheet("font-size: 18px; font-weight: bold; margin-bottom: 10px;")
        self.layout.addWidget(title)
        
        # Create results frame
        results_frame = QFrame()
        results_frame.setFrameShape(QFrame.Shape.StyledPanel)
        results_frame.setFrameShadow(QFrame.Shadow.Raised)
        results_layout = QVBoxLayout(results_frame)
        
        for result in results:
            result_widget = QWidget()
            result_layout = QVBoxLayout(result_widget)
            
            # Title with link
            title_label = QLabel(f'<a href="{result["url"]}" style="text-decoration:none; color:#1a0dab; font-size:16px;">{result["title"]}</a>')
            title_label.setOpenExternalLinks(True)
            result_layout.addWidget(title_label)
            
            # URL display
            url_label = QLabel(result["url"])
            url_label.setStyleSheet("color: #006621; font-size: 12px;")
            result_layout.addWidget(url_label)
            
            # Description
            content_label = QLabel(result["content"])
            content_label.setWordWrap(True)
            content_label.setStyleSheet("color: #545454;")
            result_layout.addWidget(content_label)
            
            results_layout.addWidget(result_widget)
            results_layout.addWidget(QFrame(frameShape=QFrame.Shape.HLine, frameShadow=QFrame.Shadow.Sunken))
            
        self.layout.addWidget(results_frame)
        
        # Add some spacing at the bottom
        self.layout.addStretch()

# Extend MainWindow with new methods
def get_home_page(self):
    settings = QSettings("NullBrowser", "Preferences")
    return settings.value("home_page", "http://localhost:8000")

# Add the get_home_page method to MainWindow
MainWindow.get_home_page = get_home_page