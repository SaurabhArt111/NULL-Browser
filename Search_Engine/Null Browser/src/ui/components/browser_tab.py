from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, 
                             QPushButton, QLabel, QMenu, QSplitter)
from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEnginePage
from PyQt6.QtWebEngineCore import QWebEngineProfile
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QApplication
import os

class BrowserWebEnginePage(QWebEnginePage):
    def __init__(self, profile, parent=None):
        super().__init__(profile, parent)
        self._view = parent
        
    def javaScriptConsoleMessage(self, level, message, line, source):
        # Capture console messages for developer tools
        pass
        
    def createWindow(self, window_type):
        # Create a new window/tab when requested
        from PyQt6.QtWebEngineCore import QWebEnginePage
        if window_type == QWebEnginePage.WebWindowType.WebBrowserTab:
            # Create new tab
            return self._view.createWindow(window_type)
        elif window_type == QWebEnginePage.WebWindowType.WebBrowserWindow:
            # Create new window
            return self._view.createWindow(window_type)
        return None

class BrowserTab(QWidget):
    url_changed = pyqtSignal(str)
    title_changed = pyqtSignal(str)
    loading_changed = pyqtSignal(bool)
    
    def __init__(self, parent=None, profile=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        # Create web view. A custom (e.g. off-the-record/InPrivate) profile
        # can be supplied by the main window; otherwise fall back to the
        # shared default profile used by normal browsing windows.
        profile = profile or QWebEngineProfile.defaultProfile()
        self.web_view = QWebEngineView()
        self.web_page = BrowserWebEnginePage(profile, self.web_view)
        self.web_view.setPage(self.web_page)
        
        # Set up context menu policy
        self.web_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.web_view.customContextMenuRequested.connect(self.show_context_menu)
        
        # Connect signals
        self.web_view.urlChanged.connect(self.handle_url_changed)
        self.web_view.titleChanged.connect(self.handle_title_changed)
        self.web_view.loadStarted.connect(lambda: self.loading_changed.emit(True))
        self.web_view.loadFinished.connect(lambda: self.loading_changed.emit(False))
        
        # Create find bar (hidden by default)
        self.find_bar = QWidget()
        find_layout = QHBoxLayout(self.find_bar)
        find_layout.setContentsMargins(5, 0, 5, 0)
        
        self.find_text = QLineEdit()
        self.find_text.setPlaceholderText("Find in page...")
        self.find_text.returnPressed.connect(self.find_next)
        find_layout.addWidget(self.find_text)
        
        self.find_next_btn = QPushButton("Next")
        self.find_next_btn.clicked.connect(self.find_next)
        find_layout.addWidget(self.find_next_btn)
        
        self.find_prev_btn = QPushButton("Previous")
        self.find_prev_btn.clicked.connect(self.find_previous)
        find_layout.addWidget(self.find_prev_btn)
        
        self.find_close_btn = QPushButton("Close")
        self.find_close_btn.clicked.connect(self.toggle_find)
        find_layout.addWidget(self.find_close_btn)
        
        self.find_bar.setVisible(False)
        
        # Add widgets to layout
        self.layout.addWidget(self.web_view)
        self.layout.addWidget(self.find_bar)
        
        # The caller (MainWindow.add_new_tab) is responsible for loading the
        # initial page - either a real URL or the offline New Tab page - so
        # we no longer hard-navigate to a local server that may not be running.
        
    def show_context_menu(self, pos):
        # Get the page and hit test result. Some PyQt/WebEngine builds expose
        # a different API surface, so fall back gracefully when the older
        # hitTestContent method is unavailable.
        page = self.web_view.page()
        hit_test = None
        link_url = None
        try:
            if hasattr(page, "hitTestContent"):
                hit_test = page.hitTestContent(pos)
                if hit_test is not None and hasattr(hit_test, "linkUrl"):
                    link_url = hit_test.linkUrl()
        except Exception:
            hit_test = None
            link_url = None
        
        # Create menu
        menu = QMenu(self)
        
        # Add actions based on hit test result
        if link_url is not None and link_url.isValid():
            # Link actions
            url = link_url
            
            open_action = menu.addAction("Open link")
            open_action.triggered.connect(lambda: self.web_view.load(url))
            
            open_new_tab_action = menu.addAction("Open link in new tab")
            open_new_tab_action.triggered.connect(lambda: self.parent().parent().add_new_tab(url.toString()))
            
            open_new_window_action = menu.addAction("Open link in new window")
            open_new_window_action.triggered.connect(lambda: self.open_in_new_window(url.toString()))
            
            open_incognito_action = menu.addAction("Open link in InPrivate window")
            open_incognito_action.triggered.connect(lambda: self.open_in_private_window(url.toString()))
            
            open_split_screen_action = menu.addAction("Open link in split screen window")
            open_split_screen_action.triggered.connect(lambda: self.open_in_split_screen(url.toString()))
            
            menu.addSeparator()
            
            copy_link_action = menu.addAction("Copy link address")
            copy_link_action.triggered.connect(lambda: self.copy_to_clipboard(url.toString()))
            
            save_link_action = menu.addAction("Save link as...")
            save_link_action.triggered.connect(lambda: self.save_link_as(url))
            
        # General options
        if menu.actions():
            menu.addSeparator()
            
        back_action = menu.addAction("Back")
        back_action.triggered.connect(self.web_view.back)
        back_action.setEnabled(self.web_view.history().canGoBack())
        
        forward_action = menu.addAction("Forward")
        forward_action.triggered.connect(self.web_view.forward)
        forward_action.setEnabled(self.web_view.history().canGoForward())
        
        reload_action = menu.addAction("Reload")
        reload_action.triggered.connect(self.web_view.reload)
        
        menu.addSeparator()
        
        view_source_action = menu.addAction("View page source")
        view_source_action.triggered.connect(self.view_source)
        
        # Check if we have any actions
        if menu.actions():
            menu.exec(self.web_view.mapToGlobal(pos))
        
    def handle_url_changed(self, url):
        self.url_changed.emit(url.toString())
        
    def handle_title_changed(self, title):
        self.title_changed.emit(title)
        
    def toggle_find(self):
        self.find_bar.setVisible(not self.find_bar.isVisible())
        if self.find_bar.isVisible():
            self.find_text.setFocus()
            self.find_text.selectAll()
            
    def find_next(self):
        text = self.find_text.text()
        if text:
            self.web_view.findText(text)
            
    def find_previous(self):
        text = self.find_text.text()
        if text:
            self.web_view.findText(text, QWebEnginePage.FindFlag.FindBackward)
            
    def zoom_in(self):
        current_zoom = self.web_view.zoomFactor()
        self.web_view.setZoomFactor(current_zoom + 0.1)
        
    def zoom_out(self):
        current_zoom = self.web_view.zoomFactor()
        if current_zoom > 0.2:  # Prevent too small zoom
            self.web_view.setZoomFactor(current_zoom - 0.1)
            
    def reset_zoom(self):
        self.web_view.setZoomFactor(1.0)
        
    def createWindow(self, window_type):
        # Create a new window or tab based on the request
        try:
            main_window = self.parent().parent()
        except Exception:
            main_window = None

        # WebDialog is the type used for chrome-less popup windows, which is
        # exactly the kind of window ad/scam scripts spawn via window.open().
        # Block them when the popup blocker is enabled, similar to Brave.
        if window_type == QWebEnginePage.WebWindowType.WebDialog:
            blocked = getattr(main_window, "block_popups", True)
            if blocked:
                if main_window is not None:
                    try:
                        main_window.statusBar().showMessage("Popup blocked", 3000)
                    except Exception:
                        pass
                return None

        if window_type == QWebEnginePage.WebWindowType.WebBrowserTab:
            # Create a new tab
            return self.parent().parent().add_new_tab_with_web_view()
        elif window_type == QWebEnginePage.WebWindowType.WebBrowserWindow:
            # Create a new window
            return self.open_in_new_window_with_webview()
        return None
        
    def copy_to_clipboard(self, text):
        # Copy text to clipboard
        clipboard = QApplication.clipboard()
        clipboard.setText(text)
        
    def view_source(self):
        # View page source
        self.parent().parent().view_page_source()
        
    def save_link_as(self, url):
        # Save link as file
        from PyQt6.QtWidgets import QFileDialog
        file_dialog = QFileDialog(self)
        file_dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        file_dialog.setNameFilter("All Files (*)")
        
        if file_dialog.exec():
            file_path = file_dialog.selectedFiles()[0]
            # Start download
            download_item = self.web_view.page().download(url)
            download_item.setDownloadFileName(file_path)
            download_item.accept()
            
    def open_in_new_window(self, url):
        # Open URL in new window
        self.parent().parent().new_window(url)
        
    def open_in_private_window(self, url):
        # Open URL in private window
        self.parent().parent().new_private_window(url)
        
    def open_in_split_screen(self, url):
        # Open URL in split screen (a simplified implementation)
        main_window = self.parent().parent()
        
        # Create a new tab
        new_tab = main_window.add_new_tab(url)
        
        # Create a splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Add the current tab and new tab to the splitter
        current_tab_index = main_window.tabs.currentIndex()
        current_tab = main_window.tabs.widget(current_tab_index)
        
        # Remove from tab widget and add to splitter
        main_window.tabs.removeTab(current_tab_index)
        splitter.addWidget(current_tab)
        splitter.addWidget(new_tab)
        
        # Add the splitter to a new tab
        main_window.tabs.insertTab(current_tab_index, splitter, "Split View")
        main_window.tabs.setCurrentIndex(current_tab_index) 