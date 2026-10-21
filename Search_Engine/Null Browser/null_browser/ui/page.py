"""The Qt WebEngine page and view used by a tab: navigation gate, JS dialogs, context-menu hook."""
import logging
import time

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWebEngineCore import QWebEnginePage
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import (QInputDialog, QMessageBox)

from ..constants import SCHEME
from ..core import crash
from ..privacy.cosmetic import TOKEN as COSMETIC_TOKEN
from ..core.permissions import ASK_PREFIX
from .autoscroll import PanCursorFilter

log = logging.getLogger("null.tab")
NAV = QWebEnginePage.NavigationType
EXTERNAL_OK = {"http", "https", "file", SCHEME, "view-source", "data", "blob", "about", "ftp", "javascript", "qrc",
               "filesystem", "devtools", "chrome-devtools"}


class BrowserPage(QWebEnginePage):
    def __init__(self, profile, tab):
        super().__init__(profile, tab)
        self.tab = tab
        self.console = []
        tab.app.video.attach(self)                          # exposes the H.264 conversion bridge when it is on and ffmpeg is present

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
                    # fb:// instagram:// twitter:// reddit:// intent:// ... : sites fire these at load to push their app.
                    # Only a real click may open a prompt; anything else is dropped silently (like Chrome does).
                    if nav_type in (NAV.NavigationTypeLinkClicked, NAV.NavigationTypeTyped):
                        self.tab.open_external(url)
                    return False
                self.tab.before_navigation(url)
            return True
        except Exception:
            log.exception("acceptNavigationRequest")
            return True

    def javaScriptConsoleMessage(self, level, message, line, source):
        if message == COSMETIC_TOKEN:                        # ping from the cosmetic filter's in-page observer (not a real console message)
            self.tab.app.adblock.cosmetic.kick(self)
            return
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
        self.pan_cursor = PanCursorFilter(self)         # Chrome-style cursor for middle-click auto-scroll

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
