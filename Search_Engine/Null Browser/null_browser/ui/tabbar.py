"""Chrome-style tab strip: adaptive widths, pinned tabs, audio buttons, loading spinner, drag reorder."""
import logging

from PyQt6.QtCore import QEvent, QPoint, QPointF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QCursor, QMouseEvent
from PyQt6.QtWidgets import QApplication, QFrame, QHBoxLayout, QMenu, QTabBar, QToolButton, QWidget

from . import icons
from .tips import tip

log = logging.getLogger("null.tabbar")


class TabStrip(QTabBar):
    closeRequested = pyqtSignal(int)
    newTabRequested = pyqtSignal()
    menuAction = pyqtSignal(str, int)         # action name, tab index
    audioToggled = pyqtSignal(int)

    PINNED_W, MIN_W, MAX_W = 46, 52, 240
    TEAR = 14                                  # px beyond the strip before a drag turns into a new window
    reserved = 270                             # width taken by search / + / window buttons (set by the window)

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
        self.setMouseTracking(True)
        self.pinned = set()
        self._press = None                     # (index, local pos, global pos) of the tab under the mouse button
        self._drag = None                      # active TabDrag
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
        avail = max(200, (self.parentWidget().width() if self.parentWidget() else 1000) - self.reserved) - pinned * self.PINNED_W
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
                tip(b, "Close tab", "Close this tab", "Ctrl+W")
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
            tip(audio, "Unmute tab" if muted else "Mute tab", "This tab is playing sound" if not muted else "Sound is muted for this tab", "Ctrl+Shift+M")
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
    def mousePressEvent(self, ev):
        i = self.tabAt(ev.position().toPoint())
        if ev.button() == Qt.MouseButton.LeftButton and i >= 0:
            self._press = (i, ev.position().toPoint(), ev.globalPosition().toPoint())
        elif i < 0:
            ev.ignore()                                    # empty strip area drags the window
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._drag is not None:
            self._drag.move(ev.globalPosition().toPoint())
            return
        if self._press is not None and ev.buttons() & Qt.MouseButton.LeftButton:
            idx, ppos, gpos = self._press
            pos = ev.position().toPoint()
            g = ev.globalPosition().toPoint()
            win = self.window()
            if self.count() == 1:
                far = (g - gpos).manhattanLength() > 6                     # the only tab: drag the whole window
            else:
                geo = win.frameGeometry()
                far = (pos.y() < -self.TEAR or pos.y() > self.height() + self.TEAR
                       or g.x() < geo.left() - 60 or g.x() > geo.right() + 60)
            if far:
                from .tabdrag import TabDrag
                self._drag = TabDrag(self, idx, ppos, g)
                self._press = None
                return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if self._drag is not None:
            drag, self._drag = self._drag, None
            drag.finish(ev.globalPosition().toPoint())
            return
        self._press = None
        if ev.button() == Qt.MouseButton.MiddleButton:
            i = self.tabAt(ev.position().toPoint())
            if i >= 0:
                self.closeRequested.emit(i)
                return
        super().mouseReleaseEvent(ev)

    def finish_qt_drag(self, ev_pos, global_pos):
        """End QTabBar's own reorder-drag before we take the tab away from it."""
        fake = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(ev_pos), QPointF(global_pos), Qt.MouseButton.LeftButton,
                           Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
        QTabBar.mouseReleaseEvent(self, fake)

    def mouseDoubleClickEvent(self, ev):
        if self.tabAt(ev.position().toPoint()) < 0:
            ev.ignore()                                    # double-click on empty strip toggles maximise (handled by the strip)
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
            add("Move tab to new window", "new_window", "external", self.count() > 1)
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


class TitleStrip(QWidget):
    """The merged title bar: tabs + new-tab button + draggable empty space + minimise / maximise / close."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setObjectName("tabstrip")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMouseTracking(True)
        self._manual = None                                # fallback window drag (platforms without system move)

    # -- dragging the window by the empty part of the strip ------------------------------------------
    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            if self.win.isMaximized() or self.win.isFullScreen():
                self._manual = None
            handle = self.win.windowHandle()
            ok = False
            try:
                ok = bool(handle and handle.startSystemMove())
            except Exception:
                ok = False
            if not ok:
                self._manual = ev.globalPosition().toPoint() - self.win.frameGeometry().topLeft()
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._manual is not None and ev.buttons() & Qt.MouseButton.LeftButton and not self.win.isMaximized():
            self.win.move(ev.globalPosition().toPoint() - self._manual)
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        self._manual = None
        super().mouseReleaseEvent(ev)

    def mouseDoubleClickEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._manual = None
            self.win.toggle_maximized()
            ev.accept()
            return
        super().mouseDoubleClickEvent(ev)


class WindowControls(QWidget):
    """[ - ][ □ ][ x ] flush with the right edge, drawn with our own icons (works on every OS)."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setObjectName("wincontrols")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.min_btn, self.max_btn, self.close_btn = QToolButton(), QToolButton(), QToolButton()
        for b, name, fn in ((self.min_btn, "wc_min", win.showMinimized), (self.max_btn, "wc_max", win.toggle_maximized),
                            (self.close_btn, "wc_close", win.close)):
            b.setObjectName(name)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setFixedSize(46, 36)
            b.setIconSize(QSize(14, 14))
            b.clicked.connect(lambda _=False, f=fn: f())
            lay.addWidget(b)
        tip(self.min_btn, "Minimize", "Send this window to the taskbar")
        tip(self.close_btn, "Close window", "Close every tab in this window", "Alt+F4")
        self.refresh()

    def refresh(self):
        w, ic = self.win, self.win.icon
        maxed = w.isMaximized()
        self.min_btn.setIcon(self._hover_icon("minimize"))
        self.max_btn.setIcon(self._hover_icon("restore" if maxed else "maximize"))
        self.close_btn.setIcon(self._hover_icon("close", hover="#ffffff"))
        tip(self.max_btn, "Restore down" if maxed else "Maximize", "Return the window to its previous size" if maxed else "Fill the whole screen", "Double-click the title bar")

    def _hover_icon(self, name, hover=None):
        win = self.win
        color = win.pal["text"]
        ic = icons.icon(name, color, 14)
        if hover:
            ic.addPixmap(icons.pixmap(name, hover, 14), icons.QIcon.Mode.Active)
        return ic
