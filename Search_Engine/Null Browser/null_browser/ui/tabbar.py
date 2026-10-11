"""Chrome-style tab strip: adaptive widths, pinned tabs, audio buttons, loading spinner, drag reorder."""
import logging

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu, QTabBar, QToolButton

from . import icons

log = logging.getLogger("null.tabbar")


class TabStrip(QTabBar):
    closeRequested = pyqtSignal(int)
    newTabRequested = pyqtSignal()
    menuAction = pyqtSignal(str, int)         # action name, tab index
    audioToggled = pyqtSignal(int)

    PINNED_W, MIN_W, MAX_W = 46, 52, 240

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setExpanding(False)
        self.setMovable(True)
        self.setDocumentMode(True)
        self.setDrawBase(False)
        self.setElideMode(Qt.TextElideMode.ElideRight)
        self.setUsesScrollButtons(True)
        self.setSelectionBehaviorOnRemove(QTabBar.SelectionBehavior.SelectPreviousTab)
        self.setIconSize(QSize(16, 16))
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.pinned = set()
        self._loading = set()
        self._frames = []
        self._frame = 0
        self._timer = QTimer(self, interval=80)
        self._timer.timeout.connect(self._spin)
        self.restyle()

    def restyle(self):
        self._frames = icons.spinner_frames(self.app.accent)

    # -- sizing --------------------------------------------------------------------------
    def tabSizeHint(self, index):
        h = 40
        if index in self.pinned or self.tabData(index) == "pinned":
            return QSize(self.PINNED_W, h)
        n = self.count()
        pinned = sum(1 for i in range(n) if self.tabData(i) == "pinned")
        avail = max(200, (self.parentWidget().width() if self.parentWidget() else 1000) - 90) - pinned * self.PINNED_W
        unpinned = max(1, n - pinned)
        w = max(self.MIN_W, min(self.MAX_W, avail // unpinned))
        return QSize(w, h)

    def minimumTabSizeHint(self, index):
        return QSize(self.PINNED_W if self.tabData(index) == "pinned" else self.MIN_W, 40)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.updateGeometry()

    # -- per-tab widgets ---------------------------------------------------------------------
    def decorate(self, index, pinned, audible, muted):
        self.setTabData(index, "pinned" if pinned else "")
        close = self.tabButton(index, QTabBar.ButtonPosition.RightSide)
        if pinned:
            if close:
                close.hide()
                self.setTabButton(index, QTabBar.ButtonPosition.RightSide, None)
        else:
            if close is None or not isinstance(close, QToolButton):
                b = QToolButton()
                b.setObjectName("tabclose")
                b.setIcon(self.app.icon("close", size=14))
                b.setIconSize(QSize(12, 12))
                b.setToolTip("Close tab")
                b.setCursor(Qt.CursorShape.ArrowCursor)
                b.clicked.connect(lambda _=False, btn=b: self._close_clicked(btn))
                self.setTabButton(index, QTabBar.ButtonPosition.RightSide, b)
        audio = self.tabButton(index, QTabBar.ButtonPosition.LeftSide)
        if (audible or muted) and not pinned:
            if audio is None:
                audio = QToolButton()
                audio.setObjectName("tabaudio")
                audio.clicked.connect(lambda _=False, btn=audio: self._audio_clicked(btn))
                self.setTabButton(index, QTabBar.ButtonPosition.LeftSide, audio)
            audio.setIcon(self.app.icon("mute" if muted else "volume", size=14))
            audio.setIconSize(QSize(13, 13))
            audio.setToolTip("Unmute tab" if muted else "Mute tab")
        elif audio is not None:
            self.setTabButton(index, QTabBar.ButtonPosition.LeftSide, None)
            audio.deleteLater()

    def _find(self, btn, pos):
        for i in range(self.count()):
            if self.tabButton(i, pos) is btn:
                return i
        return -1

    def _close_clicked(self, btn):
        i = self._find(btn, QTabBar.ButtonPosition.RightSide)
        if i >= 0:
            self.closeRequested.emit(i)

    def _audio_clicked(self, btn):
        i = self._find(btn, QTabBar.ButtonPosition.LeftSide)
        if i >= 0:
            self.audioToggled.emit(i)

    # -- loading spinner ---------------------------------------------------------------------------
    def set_loading(self, index, loading):
        (self._loading.add if loading else self._loading.discard)(index)
        if self._loading and not self._timer.isActive():
            self._timer.start()
        elif not self._loading:
            self._timer.stop()

    def clear_loading(self):
        self._loading.clear()
        self._timer.stop()

    def _spin(self):
        self._frame = (self._frame + 1) % len(self._frames)
        for i in list(self._loading):
            if 0 <= i < self.count():
                self.setTabIcon(i, self._frames[self._frame])

    # -- input ----------------------------------------------------------------------------------------
    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.MouseButton.MiddleButton:
            i = self.tabAt(ev.pos())
            if i >= 0:
                self.closeRequested.emit(i)
                return
        super().mouseReleaseEvent(ev)

    def mouseDoubleClickEvent(self, ev):
        if self.tabAt(ev.pos()) < 0:
            self.newTabRequested.emit()
        else:
            super().mouseDoubleClickEvent(ev)

    def _menu(self, pos):
        i = self.tabAt(pos)
        m = QMenu(self)
        add = lambda text, name, ic=None, en=True: self._act(m, text, name, i, ic, en)
        add("New tab", "new", "plus")
        if i >= 0:
            m.addSeparator()
            add("Reload", "reload", "reload")
            add("Duplicate", "duplicate", "copy")
            add("Unpin tab" if self.tabData(i) == "pinned" else "Pin tab", "pin", "pin")
            add("Unmute site" if self.app.tab_muted(i, self) else "Mute site", "mute", "mute")
            m.addSeparator()
            add("Close tab", "close", "close")
            add("Close other tabs", "close_others", None, self.count() > 1)
            add("Close tabs to the right", "close_right", None, i < self.count() - 1)
        add("Reopen closed tab", "reopen", "history", bool(self.app.closed_tabs))
        m.exec(self.mapToGlobal(pos))
        m.deleteLater()

    def _act(self, menu, text, name, idx, ic, enabled):
        a = QAction(text, menu)
        if ic:
            a.setIcon(self.app.icon(ic))
        a.setEnabled(enabled)
        a.triggered.connect(lambda: self.menuAction.emit(name, idx))
        menu.addAction(a)
