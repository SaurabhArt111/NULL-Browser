"""Developer tools for a tab: docked right / bottom or in a window, switchable while open.

Shortcuts (see window.py): F12 / Ctrl+Shift+I toggle, Ctrl+Shift+J opens the Console, Ctrl+Shift+C starts "select an element",
Ctrl+Shift+M toggles device mode (devicemode.py), Ctrl+U shows the page source.

The DevTools frontend is Chromium's own page. Qt gives it no hooks for panels or element picking, so those are driven by
dispatching the same mouse events a click would: the frontend's buttons and tabs live in shadow DOM, which the small
finder below walks.
"""
import logging

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PyQt6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget)

from . import icons
from .page import _DevToolsView
from .tips import tip

log = logging.getLogger("null.tab")
WA = QWebEngineSettings.WebAttribute

# Walks the frontend's DOM including shadow roots. `pick(el)` chooses the element; `act` is what to do with it.
_FIND = """
(() => {
  const walk = (root) => {
    for (const el of root.querySelectorAll('*')) {
      if (PICK) return el;
      if (el.shadowRoot) { const x = walk(el.shadowRoot); if (x) return x; }
    }
    return null;
  };
  const el = walk(document);
  ACT
})()
"""
_CLICK = ("if (!el) return false; for (const t of ['pointerdown','mousedown','pointerup','mouseup','click']) "
          "el.dispatchEvent(new MouseEvent(t, {bubbles:true, composed:true, cancelable:true, button:0, view:window})); return true;")
_INSPECT = "el.tagName === 'BUTTON' && (el.title || '').startsWith('Select an element')"


def _script(pick, act):
    return _FIND.replace("PICK", pick).replace("ACT", "return (() => { " + act + " })();" if act else "return !!el;")


def _tab_pick(label):
    return f"el.getAttribute('role') === 'tab' && el.getAttribute('aria-label') === '{label}'"


class DevToolsMixin:
    """Docked / windowed developer tools."""

    @property
    def devtools_visible(self):
        return self.devtools is not None

    # ---- entry points -------------------------------------------------------------------------------------------
    def toggle_devtools(self, inspect=False):
        """F12 / Ctrl+Shift+I. With inspect=True (context-menu "Inspect") opens and picks the element that was right-clicked."""
        if self.devtools is not None and not inspect:
            return self.close_devtools()
        if inspect:
            self.show_devtools(then=lambda: self.page.triggerAction(QWebEnginePage.WebAction.InspectElement))
        else:
            self.show_devtools()

    def show_devtools(self, panel=None, then=None):
        """Open the tools if they are closed, optionally switch to a panel ("Console", "Network"...) and run `then`."""
        fresh = self.devtools is None
        if fresh:
            self.open_devtools()
        elif self.dock_mode() == "window":
            self.devtools.raise_()
            self.devtools.activateWindow()

        def ready():
            if self.devtools is None:
                return
            if panel:
                self.devtools_panel(panel)
            if then:
                then()
        self._when_frontend_ready(ready)

    def devtools_console(self):
        """Ctrl+Shift+J."""
        self.show_devtools(panel="Console", then=self._focus_devtools)

    def devtools_inspect(self):
        """Ctrl+Shift+C: toggles "select an element in the page", opening the tools first when needed."""
        def go():
            self._frontend_js(_script(_INSPECT, _CLICK))
        if self.devtools is None:
            self.show_devtools(panel="Elements", then=go)
        else:
            self._when_frontend_ready(go)

    def devtools_panel(self, label):
        self._frontend_js(_script(_tab_pick(label), _CLICK))

    # ---- frontend helpers ---------------------------------------------------------------------------------------
    def _frontend_js(self, source, callback=None):
        if self.devtools is not None:
            self.devtools.page().runJavaScript(source, callback) if callback else self.devtools.page().runJavaScript(source)

    def _when_frontend_ready(self, fn, tries=60):
        """The frontend takes a moment to draw its toolbar after the page has loaded; poll until the inspect button exists."""
        if self.devtools is None:
            return

        def got(found):
            if self.devtools is None:
                return
            if found:
                fn()
            elif tries > 0:
                QTimer.singleShot(150, lambda: self._when_frontend_ready(fn, tries - 1))
            else:
                log.warning("DevTools frontend did not become ready")
        self.devtools.page().runJavaScript(_script(_INSPECT, ""), got)

    def _focus_devtools(self):
        if self.devtools is not None:
            self.devtools.setFocus()

    def dock_mode(self):
        return getattr(self, "_dock", None) or self.app.settings.get("devtools_dock") or "right"

    # ---- open / place / close -----------------------------------------------------------------------------------
    def open_devtools(self):
        view = _DevToolsView()
        dev_page = QWebEnginePage(self.profile, view)
        view.setPage(dev_page)
        self.page.setDevToolsPage(dev_page)
        self.devtools = view
        dev_page.loadFinished.connect(lambda _ok: self._restyle_devtools())
        dev_page.windowCloseRequested.connect(lambda: QTimer.singleShot(0, self.close_devtools))   # the frontend's own close button
        view.closeRequested.connect(lambda: QTimer.singleShot(0, self.close_devtools))
        self._place_devtools(self.app.settings.get("devtools_dock") or "right")
        self.schedule_viewport_sync()

    def _detach_devtools(self):
        """Take the view out of whatever holds it (dock host or window) without destroying it."""
        view, host = self.devtools, self.devtools_host
        self.devtools_host = None
        if host is not None:
            view.setParent(None)
            host.setParent(None)
            host.deleteLater()
        else:
            view.hide()

    def _place_devtools(self, dock):
        view = self.devtools
        self._dock = dock
        if dock == "window":
            view.setParent(None)
            view.setWindowTitle(f"DevTools - {self.title()}")
            view.setWindowIcon(icons.app_icon())
            view.resize(1100, 760)
            view.show()
            return
        host = QWidget(self)
        host.setObjectName("devtoolsHost")
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._devtools_header(host, dock))
        layout.addWidget(view, 1)
        view.show()
        self.devtools_host = host
        self._restyle_devtools()
        bottom = dock == "bottom"
        self.split.setOrientation(Qt.Orientation.Vertical if bottom else Qt.Orientation.Horizontal)
        self.split.addWidget(host)
        host.setMinimumSize(0 if bottom else 300, 160 if bottom else 0)
        total = self.split.height() if bottom else self.split.width()
        ratio = min(0.8, max(0.15, float(self.app.settings.get("devtools_size") or 0.42)))
        self.split.setSizes([int(total * (1 - ratio)), int(total * ratio)])
        try:
            self.split.splitterMoved.disconnect(self._devtools_moved)
        except TypeError:
            pass
        self.split.splitterMoved.connect(self._devtools_moved)

    def _devtools_header(self, host, dock):
        colors = self.app.pal(self.private)
        header = QFrame(host)
        header.setObjectName("devtoolsHeader")
        row = QHBoxLayout(header)
        row.setContentsMargins(12, 2, 6, 2)
        row.setSpacing(2)
        self.devtools_title = QLabel("Developer tools", header)
        self.devtools_title.setObjectName("devtoolsTitle")
        row.addWidget(self.devtools_title)
        row.addStretch(1)
        group = QButtonGroup(header)
        group.setExclusive(True)
        for mode, icon, title, hint in (("right", "dock_right", "Dock to right", "Tools beside the page"),
                                         ("bottom", "dock_bottom", "Dock to bottom", "Tools below the page"),
                                         ("window", "external_window", "Open in a window", "Tools in their own window")):
            b = QToolButton(header)
            b.setObjectName("devtoolsDock")
            b.setCheckable(True)
            b.setChecked(mode == dock)
            b.setAutoRaise(True)
            b.setIcon(icons.icon(icon, colors["text"], 16))
            tip(b, title, hint)
            b.clicked.connect(lambda _c=False, m=mode: self.set_devtools_dock(m))
            group.addButton(b)
            row.addWidget(b)
        close = QToolButton(header)
        close.setObjectName("devtoolsClose")
        close.setText("✕")
        tip(close, "Close developer tools", "Hide the panel", "F12")
        close.clicked.connect(self.close_devtools)
        row.addWidget(close)
        return header

    def set_devtools_dock(self, mode):
        """Move the open tools to another side (or into a window) and remember the choice."""
        if mode not in ("right", "bottom", "window"):
            return
        self.app.settings.set("devtools_dock", mode)
        if self.devtools is None or mode == self.dock_mode():
            return
        self._detach_devtools()
        self._place_devtools(mode)
        self.schedule_viewport_sync()

    def _devtools_moved(self, *_a):
        if not hasattr(self, "_size_timer"):
            self._size_timer = QTimer(self)
            self._size_timer.setSingleShot(True)
            self._size_timer.setInterval(400)
            self._size_timer.timeout.connect(self._save_devtools_size)
        if self.devtools_host is not None:
            self._size_timer.start()

    def _save_devtools_size(self):
        if self.devtools_host is None:
            return
        sizes = self.split.sizes()
        if len(sizes) == 2 and sum(sizes) > 0:
            self.app.settings.set("devtools_size", round(sizes[1] / sum(sizes), 3))

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
        self._dock = None
        view.hide()
        if host is not None:
            host.setParent(None)
            host.deleteLater()
        else:
            view.setParent(None)
            view.deleteLater()
        self.schedule_viewport_sync()
