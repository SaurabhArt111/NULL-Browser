"""Window frame, resizing and fullscreen handling."""
import logging

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from ..core import crash
from . import enhance, winframe

log = logging.getLogger("null.window")


class WindowFrameMixin:
    """Frameless-window behaviour: native frame on Windows, edge resize, maximise, fullscreen, live-resize."""

    def _ensure_native_frame(self):
        """Windows: turn the frameless window into a real resizable window (snap, shadow, animations). Idempotent."""
        if not winframe.IS_WIN:
            return
        if winframe.install(self):
            self._native_frame = True
            self.snap_layouts = winframe.supports_snap_layouts()
            self._update_border()
            winframe.set_background(self, QColor(self.pal["bar"]))

    def showEvent(self, ev):
        super().showEvent(ev)
        if winframe.IS_WIN and enhance.ENABLED and enhance.NATIVE_FRAME:
            try:
                if not self._native_frame or winframe.registered_hwnd(self) != int(self.winId()):
                    self._ensure_native_frame()               # first show, or Qt gave the window a new native handle
            except Exception:
                crash.log.debug("native frame (show)", exc_info=True)

    def _update_border(self):
        # With the native frame Windows owns the resize edges, so no margin is needed (and no gap shows around the page).
        b = 0 if (self._native_frame or self.isMaximized() or self.isFullScreen()) else self.BORDER
        self.setContentsMargins(b, b, b, b)

    def begin_live_resize(self):
        """Windows is running a drag-resize / move loop: keep the window cheap to repaint until it ends."""
        self._live_resize = True

    def end_live_resize(self):
        self._live_resize = False
        self._bm_timer.start()                            # the bookmarks bar is rebuilt once, after the drag
        self.update()

    def toggle_maximized(self):
        if self.isFullScreen():
            return
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def changeEvent(self, ev):
        super().changeEvent(ev)
        if ev.type() == ev.Type.WindowStateChange:
            self._update_border()
            if hasattr(self, "wc"):
                self.wc.refresh()

    def _edges_at(self, pos):
        if self._native_frame or self.isMaximized() or self.isFullScreen():
            return Qt.Edge(0)
        x, y, w, h, m, c = pos.x(), pos.y(), self.width(), self.height(), self.BORDER, self.CORNER
        near_h, near_v = (y < m or y >= h - m), (x < m or x >= w - m)
        left = x < m or (x < c and near_h)
        right = x >= w - m or (x >= w - c and near_h)
        top = y < m or (y < c and near_v)
        bottom = y >= h - m or (y >= h - c and near_v)
        e = Qt.Edge(0)
        if left:
            e |= Qt.Edge.LeftEdge
        if right:
            e |= Qt.Edge.RightEdge
        if top:
            e |= Qt.Edge.TopEdge
        if bottom:
            e |= Qt.Edge.BottomEdge
        return e

    def mouseMoveEvent(self, ev):
        e = self._edges_at(ev.position().toPoint())
        L, R, T, B = Qt.Edge.LeftEdge, Qt.Edge.RightEdge, Qt.Edge.TopEdge, Qt.Edge.BottomEdge
        if e in (L | T, R | B):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif e in (R | T, L | B):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif e in (L, R):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif e in (T, B):
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(ev)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            e = self._edges_at(ev.position().toPoint())
            if e:
                handle = self.windowHandle()
                if handle is not None and handle.startSystemResize(e):
                    ev.accept()
                    return
        super().mousePressEvent(ev)

    def leaveEvent(self, ev):
        self.unsetCursor()
        super().leaveEvent(ev)

    # ===================================================================== fullscreen / events
    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self._chrome_visible(True)
        else:
            self.showFullScreen()
            self._chrome_visible(False)

    def set_page_fullscreen(self, on):
        self.fullscreen_tab = on
        if on:
            self.showFullScreen()
        else:
            self.showNormal()
        self._chrome_visible(not on)

    def _chrome_visible(self, v):
        self.strip.setVisible(v)
        self.toolbar.setVisible(v)
        self.bmbar.setVisible(v and bool(self.app.settings.get("show_bookmarks_bar")))

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._bm_timer.start()                            # rebuild the bookmarks bar once the drag settles, not per pixel
