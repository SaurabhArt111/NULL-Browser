"""Chrome-style cursor for middle-click auto-scroll.

Chromium implements the auto-scroll itself (it works), but Qt WebEngine translates Chromium's "panning" cursors into
Qt's generic resize cursors (the four-way / horizontal / vertical resize arrows), which looks like a window-resize
cursor. This filter watches the page's render widget: after a middle-click it swaps those cursors for the round
anchor icon Chrome shows (and a small direction arrow once the mouse moves away from the anchor).

Auto-scroll ends on any click, key press, navigation or when the mouse leaves the page, which disarms the filter so
real CSS `cursor: move` / `col-resize` cursors on web pages are never touched.
"""
import math

from PyQt6.QtCore import QEvent, QObject, QPointF, Qt
from PyQt6.QtGui import QColor, QCursor, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QApplication, QWidget

CS = Qt.CursorShape
_PAN_SHAPES = {CS.SizeAllCursor, CS.SizeHorCursor, CS.SizeVerCursor, CS.SizeFDiagCursor, CS.SizeBDiagCursor}
SIZE = 28                                   # logical px


def _arrow(p, cx, cy, dx, dy, r):
    """A small filled triangle pointing along (dx, dy), `r` away from the centre."""
    tip = QPointF(cx + dx * r, cy + dy * r)
    nx, ny = -dy, dx
    base = QPointF(cx + dx * (r - 4.2), cy + dy * (r - 4.2))
    path = QPainterPath()
    path.moveTo(tip)
    path.lineTo(QPointF(base.x() + nx * 3.4, base.y() + ny * 3.4))
    path.lineTo(QPointF(base.x() - nx * 3.4, base.y() - ny * 3.4))
    path.closeSubpath()
    p.drawPath(path)


def _make(direction):
    """direction: None for the resting anchor, or a (dx, dy) unit vector for a pan arrow."""
    app = QApplication.instance()
    dpr = app.primaryScreen().devicePixelRatio() if app and app.primaryScreen() else 1.0
    px = QPixmap(int(SIZE * dpr), int(SIZE * dpr))
    px.setDevicePixelRatio(dpr)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = SIZE / 2
    p.setPen(QPen(QColor(255, 255, 255, 235), 2.6))
    p.setBrush(QColor(255, 255, 255, 235))
    if direction is None:
        for d in ((0, -1), (0, 1), (-1, 0), (1, 0)):                       # outline pass (white halo)
            _arrow(p, c, c, d[0], d[1], 11.5)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(c, c), 7.6, 7.6)
        p.setPen(QPen(QColor(30, 30, 36), 1.6))
        p.setBrush(QColor(30, 30, 36))
        for d in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            _arrow(p, c, c, d[0], d[1], 11.5)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(c, c), 7.6, 7.6)
        p.setBrush(QColor(30, 30, 36))
        p.drawEllipse(QPointF(c, c), 1.9, 1.9)
    else:
        dx, dy = direction
        _arrow(p, c, c, dx, dy, 11.5)
        p.setPen(QPen(QColor(30, 30, 36), 1.6))
        p.setBrush(QColor(30, 30, 36))
        _arrow(p, c, c, dx, dy, 11.5)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(30, 30, 36), 1.6))
        p.drawEllipse(QPointF(c, c), 2.6, 2.6)
    p.end()
    return QCursor(px, int(c), int(c))


_cache = {}


def cursor_for(shape, delta):
    """Pick the cursor: anchor at rest, directional arrow while the pointer is away from the anchor."""
    key = None
    if delta is not None:
        ang = math.atan2(delta[1], delta[0])
        octant = int(round(ang / (math.pi / 4))) % 8
        key = ((1, 0), (0.707, 0.707), (0, 1), (-0.707, 0.707), (-1, 0), (-0.707, -0.707), (0, -1), (0.707, -0.707))[octant]
    if key not in _cache:
        _cache[key] = _make(key)
    return _cache[key]


class PanCursorFilter(QObject):
    """Install on a QWebEngineView; it finds (and re-finds) the render widget that actually owns the cursor."""

    def __init__(self, view):
        super().__init__(view)
        self.view = view
        self._armed = False
        self._origin = None
        self._busy = False
        self._watched = set()
        view.installEventFilter(self)
        self.attach()

    def attach(self):
        """(Re)hook the view's render widgets; Qt WebEngine creates / replaces them lazily."""
        widgets = list(self.view.findChildren(QWidget))
        if self.view.focusProxy() is not None:
            widgets.append(self.view.focusProxy())
        for w in widgets:
            if w not in self._watched:
                self._watched.add(w)
                w.installEventFilter(self)

    def disarm(self):
        self._armed = False
        self._origin = None

    def eventFilter(self, obj, ev):
        t = ev.type()
        try:
            if t == QEvent.Type.ChildAdded and obj is self.view:
                child = ev.child()
                if child is not None and child.isWidgetType():
                    child.installEventFilter(self)
                    self._watched.add(child)
            elif t == QEvent.Type.MouseButtonPress:
                if ev.button() == Qt.MouseButton.MiddleButton and not self._armed:
                    self._armed = True
                    self._origin = ev.globalPosition()
                else:                                   # any click ends auto-scroll
                    self.disarm()
            elif t == QEvent.Type.MouseButtonRelease:
                if ev.button() == Qt.MouseButton.MiddleButton and self._armed and self._origin is not None:
                    d = ev.globalPosition() - self._origin       # press-hold-drag-release (Chrome's "drag" mode) ends here
                    if math.hypot(d.x(), d.y()) > 14:
                        self.disarm()
            elif t in (QEvent.Type.KeyPress, QEvent.Type.FocusOut, QEvent.Type.Leave, QEvent.Type.Hide):
                self.disarm()
            elif t == QEvent.Type.CursorChange and self._armed and not self._busy and obj.isWidgetType():
                cur = obj.cursor()
                if cur.shape() in _PAN_SHAPES:
                    delta = None
                    if self._origin is not None:
                        d = QCursor.pos()
                        dx, dy = d.x() - self._origin.x(), d.y() - self._origin.y()
                        delta = (dx, dy) if math.hypot(dx, dy) > 14 else None
                    self._busy = True
                    try:
                        obj.setCursor(cursor_for(cur.shape(), delta))
                    finally:
                        self._busy = False
        except Exception:
            pass
        return False
