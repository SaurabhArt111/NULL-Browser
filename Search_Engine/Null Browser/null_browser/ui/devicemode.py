"""Device mode (Ctrl+Shift+M): a responsive viewport for the current tab, like Chrome's device toolbar.

The embedded DevTools frontend of Qt WebEngine has no device-toolbar button, so it is built here:

 * `Stage` holds the web view and, in device mode, sizes it to the chosen width x height (centred, never larger than the room
   there is), so CSS media queries see exactly that viewport.
 * `DeviceBar` is the strip above it: device presets, width / height, rotate, "mobile" user agent, close.
 * `DeviceModeMixin` (part of `Tab`) wires it up. The mobile user agent is applied per tab: the request interceptor swaps the
   `User-Agent` header for requests that belong to this tab's site, and a small script makes `navigator.userAgent` agree.
"""
import logging

from PyQt6.QtCore import QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWebEngineCore import QWebEngineScript
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QSpinBox, QToolButton, QWidget)

from . import icons
from .tips import tip

log = logging.getLogger("null.device")

UA_IPHONE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
             "Version/17.5 Mobile/15E148 Safari/604.1")
UA_IPAD = ("Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
           "Version/17.5 Mobile/15E148 Safari/604.1")
UA_ANDROID = ("Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/140.0.0.0 Mobile Safari/537.36")

# name, width, height, user agent ("" = keep the browser's own)
DEVICES = [
    ("Responsive", 0, 0, ""),
    ("iPhone SE", 375, 667, UA_IPHONE),
    ("iPhone 14 Pro", 393, 852, UA_IPHONE),
    ("iPhone 14 Pro Max", 430, 932, UA_IPHONE),
    ("Pixel 7", 412, 915, UA_ANDROID),
    ("Galaxy S20 Ultra", 412, 915, UA_ANDROID),
    ("iPad Mini", 768, 1024, UA_IPAD),
    ("iPad Air", 820, 1180, UA_IPAD),
    ("iPad Pro 12.9", 1024, 1366, UA_IPAD),
    ("Laptop", 1280, 800, ""),
    ("Laptop L", 1440, 900, ""),
]

_SCRIPT_NAME = "null-device-mode"
_SCRIPT = """(() => {
  const ua = %(ua)s, mobile = %(mobile)s;
  const set = (o, k, v) => { try { Object.defineProperty(o, k, {get: () => v, configurable: true}); } catch (e) {} };
  const nav = Navigator.prototype;
  set(nav, 'userAgent', ua);
  set(nav, 'appVersion', ua.replace(/^Mozilla\\//, ''));
  if (mobile) { set(nav, 'maxTouchPoints', 5); set(nav, 'platform', /iP(hone|ad)/.test(ua) ? 'iPhone' : 'Linux armv81'); set(nav, 'userAgentData', undefined); }
})();"""


class Stage(QWidget):
    """Parent of the web view. Normally the view fills it; in device mode it is a centred box of the chosen size."""
    PAD = 10

    def __init__(self, view, parent=None):
        super().__init__(parent)
        self.view = view
        view.setParent(self)
        self.size_wh = None                                # None = fill, else (w, h) in CSS px
        self.setMinimumSize(200, 120)
        self.setAutoFillBackground(False)

    def set_size(self, wh):
        self.size_wh = wh
        self.relayout()
        self.update()

    def actual(self):
        return (self.view.width(), self.view.height())

    def relayout(self, shrink=0):
        full = self.rect()
        if self.size_wh is None:
            self.view.setGeometry(full.adjusted(0, 0, -shrink, 0))
            return
        w, h = self.size_wh
        aw, ah = full.width(), full.height()
        vw, vh = min(w, aw), min(h, ah)
        x = (aw - vw) // 2
        y = self.PAD if h + 2 * self.PAD <= ah else 0
        self.view.setGeometry(QRect(x, y, vw - shrink, vh))

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.relayout()

    def nudge(self):
        """Resize the view by one pixel and back. Makes Chromium re-read the size of a view whose surface went stale."""
        self.relayout(shrink=1)
        QTimer.singleShot(40, self.relayout)

    def paintEvent(self, ev):
        if self.size_wh is None:
            return
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(self.property("stageColor") or "#2b2d3a"))
        r = self.view.geometry().adjusted(-1, -1, 0, 0)
        p.setPen(QPen(QColor(255, 255, 255, 60), 1))
        p.drawRect(r)


class DeviceBar(QFrame):
    changed = pyqtSignal()
    closeRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("devicebar")
        self._busy = False
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 4, 8, 4)
        lay.setSpacing(8)
        self.device = QComboBox()
        for name, w, h, _ua in DEVICES:
            self.device.addItem(name if not w else f"{name}  ({w}×{h})")
        self.device.setMinimumWidth(190)
        tip(self.device, "Device", "Pick a phone, tablet or laptop size, or Responsive for any size")
        self.w = QSpinBox()
        self.h = QSpinBox()
        for s in (self.w, self.h):
            s.setRange(240, 4000)
            s.setValue(412)
            s.setFixedWidth(72)
            s.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
            s.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.h.setValue(800)
        tip(self.w, "Width", "Viewport width in CSS pixels")
        tip(self.h, "Height", "Viewport height in CSS pixels")
        self.rotate = QToolButton()
        self.rotate.setAutoRaise(True)
        tip(self.rotate, "Rotate", "Swap width and height")
        self.mobile = QCheckBox("Mobile")
        tip(self.mobile, "Mobile user agent", "Send a phone / tablet User-Agent for this tab and reload to apply it")
        self.info = QLabel("")
        self.info.setObjectName("deviceinfo")
        self.close_btn = QToolButton()
        self.close_btn.setObjectName("devicebarClose")
        self.close_btn.setText("✕")
        tip(self.close_btn, "Close device mode", "Back to the full window", "Ctrl+Shift+M")
        lay.addWidget(self.device)
        lay.addWidget(self.w)
        lay.addWidget(QLabel("×"))
        lay.addWidget(self.h)
        lay.addWidget(self.rotate)
        lay.addWidget(self.mobile)
        lay.addStretch(1)
        lay.addWidget(self.info)
        lay.addWidget(self.close_btn)
        self.device.currentIndexChanged.connect(self._preset)
        self.w.valueChanged.connect(self._edited)
        self.h.valueChanged.connect(self._edited)
        self.rotate.clicked.connect(self._rotate)
        self.mobile.toggled.connect(lambda _c: None if self._busy else self.changed.emit())
        self.close_btn.clicked.connect(self.closeRequested)
        self.setStyleSheet("QFrame#devicebar{border-bottom:1px solid rgba(128,128,128,.35);}"
                           "QToolButton#devicebarClose{border-radius:6px;padding:2px 8px;}")

    def set_icons(self, color):
        self.rotate.setIcon(icons.icon("rotate", color, 16))

    def _preset(self, i):
        name, w, h, ua = DEVICES[i]
        self._busy = True
        if w:
            self.w.setValue(w)
            self.h.setValue(h)
        self.mobile.setChecked(bool(ua))
        self.w.setReadOnly(bool(w))
        self.h.setReadOnly(bool(w))
        self._busy = False
        self.changed.emit()

    def _edited(self, _v):
        if self._busy:
            return
        if self.device.currentIndex() != 0:                  # typing a size switches to "Responsive"
            self._busy = True
            self.device.setCurrentIndex(0)
            self.w.setReadOnly(False)
            self.h.setReadOnly(False)
            self._busy = False
        self.changed.emit()

    def _rotate(self):
        self._busy = True
        w, h = self.w.value(), self.h.value()
        self.w.setValue(h)
        self.h.setValue(w)
        self._busy = False
        self.changed.emit()

    def state(self):
        ua = DEVICES[self.device.currentIndex()][3]
        if self.mobile.isChecked() and not ua:
            ua = UA_ANDROID                                   # "Mobile" ticked on a free-size / laptop frame
        if not self.mobile.isChecked():
            ua = ""
        return (self.w.value(), self.h.value()), ua


class DeviceModeMixin:
    """Part of `Tab`: Ctrl+Shift+M."""
    device_active = False

    def toggle_device_mode(self):
        self.set_device_mode(not self.device_active)

    def set_device_mode(self, on):
        if on == self.device_active:
            return
        self.device_active = on
        if on:
            if self.devbar is None:
                self.devbar = DeviceBar(self)
                self.devbar.device.setCurrentIndex(4)             # Pixel 7 to start with
                self.devbar.changed.connect(self._device_changed)
                self.devbar.closeRequested.connect(lambda: self.set_device_mode(False))
                self.page_col_layout.insertWidget(0, self.devbar)
            colors = self.app.pal(self.private)
            self.devbar.set_icons(colors["text"])
            self.stage.setProperty("stageColor", colors["strip"])
            self.devbar.show()
            self._device_changed()
        else:
            if self.devbar is not None:
                self.devbar.hide()
            self._apply_ua("")
            self.stage.set_size(None)
        self.schedule_viewport_sync()

    def _device_changed(self):
        if not self.device_active or self.devbar is None:
            return
        wh, ua = self.devbar.state()
        self.stage.set_size(wh)
        QTimer.singleShot(0, self._device_info)
        self._apply_ua(ua, reload=True)
        self.schedule_viewport_sync()

    def _device_info(self):
        if self.devbar is None:
            return
        w, h = self.stage.actual()
        want = self.devbar.state()[0]
        self.devbar.info.setText("" if (w, h) == want else f"fits {w}×{h} here")

    # ---- user agent ----------------------------------------------------------------------------------------------
    def _apply_ua(self, ua, reload=False):
        changed = ua != getattr(self, "_device_ua", "")
        self._device_ua = ua
        scripts = self.page.scripts()
        for old in scripts.find(_SCRIPT_NAME):
            scripts.remove(old)
        if ua:
            import json
            s = QWebEngineScript()
            s.setName(_SCRIPT_NAME)
            s.setSourceCode(_SCRIPT % {"ua": json.dumps(ua), "mobile": "true"})
            s.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
            s.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
            s.setRunsOnSubFrames(True)
            scripts.insert(s)
        self.sync_device_ua(self.page.url().host())
        if changed and reload and self.page.url().scheme() in ("http", "https"):
            self.page.triggerAction(self.page.WebAction.Reload)

    def sync_device_ua(self, host):
        """Tell the request interceptor which site this tab is on, so its requests carry the device's User-Agent."""
        table = getattr(self.app.adblock, "device_ua", None)
        if table is None:
            return
        old = getattr(self, "_device_ua_host", "")
        if old and table.get(old) is not None and old != host:
            table.pop(old, None)
        ua = getattr(self, "_device_ua", "")
        host = (host or "").lower()
        if ua and host:
            table[host] = ua.encode()
            self._device_ua_host = host
        else:
            table.pop(old, None)
            self._device_ua_host = ""

    def end_device_mode(self):
        """Tab is closing."""
        self.sync_device_ua("")
        self.device_active = False
