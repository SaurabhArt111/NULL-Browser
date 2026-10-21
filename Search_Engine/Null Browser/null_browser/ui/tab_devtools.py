"""Developer tools host for a tab."""
import logging

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget)

from . import icons
from .page import _DevToolsView
from .tips import tip

log = logging.getLogger("null.tab")
WA = QWebEngineSettings.WebAttribute


class DevToolsMixin:
    """Docked / windowed developer tools."""

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
            tip(close, "Close developer tools", "Hide the panel", "F12")
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
