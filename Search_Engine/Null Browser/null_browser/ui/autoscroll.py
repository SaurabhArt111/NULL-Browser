"""Chrome's cursors for middle-click auto-scroll.

Chromium implements the auto-scroll itself (it works), but Qt WebEngine turns Chromium's "panning" cursors into Qt's generic
resize cursors (the four-way / horizontal / vertical resize arrows), which looks like a window-resize cursor. This filter
watches the page's render widget: after a middle-click it swaps those cursors for the ones Chrome shows on Windows:

* at rest (the anchor): a white disc with a dark centre dot and a small triangle on each scrollable side - up/down only on
  a normal page, left/right only on a sideways-scrolling area, all four where both directions scroll;
* once the pointer moves away from the anchor: a small dot with ONE triangle pointing the way the page is scrolling
  (up, down, left, right and the four diagonals when both axes scroll).

Which axes can scroll is read from the page (the scrollable element under the pointer, else the document). Drawing is
supersampled and device-pixel-ratio aware, so the cursor is crisp on HiDPI screens.

Auto-scroll ends on any click, key press, navigation or when the mouse leaves the page, which disarms the filter so real CSS
`cursor: move` / `col-resize` cursors on web pages are never touched.
"""
import math

from PyQt6.QtCore import QEvent, QObject, QPointF, Qt
from PyQt6.QtGui import QColor, QCursor, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QApplication, QWidget

CS = Qt.CursorShape
_PAN_SHAPES = {CS.SizeAllCursor, CS.SizeHorCursor, CS.SizeVerCursor, CS.SizeFDiagCursor, CS.SizeBDiagCursor}
SIZE = 32                                    # logical px (Windows cursors are at most 32x32 before DPI scaling)
DEAD_ZONE = 15                               # px the pointer must leave the anchor before a direction arrow is shown
DARK = QColor(30, 30, 30)
WHITE = QColor(255, 255, 255)

# which way the page can scroll under the pointer: runs in the page, returns "v", "h", "vh" or ""
_AXES_JS = """(function(x,y){try{
var s=document.scrollingElement||document.documentElement;
function can(el){var cs=getComputedStyle(el),root=(el===s||el===document.body);
 var v=(root||/(auto|scroll|overlay)/.test(cs.overflowY))&&el.scrollHeight>el.clientHeight+1;
 var h=(root||/(auto|scroll|overlay)/.test(cs.overflowX))&&el.scrollWidth>el.clientWidth+1;return (v?'v':'')+(h?'h':'');}
var e=document.elementFromPoint(x,y);
while(e&&e!==document.documentElement){var r=can(e);if(r&&e!==document.body)return r;e=e.parentElement;}
return can(s);}catch(err){return 'v';}})(%f,%f)"""


def _tri(p, cx, cy, dx, dy, dist, half_base, height):
    """Filled triangle pointing along (dx, dy); its tip is `dist` from (cx, cy)."""
    tip = QPointF(cx + dx * dist, cy + dy * dist)
    bx, by = cx + dx * (dist - height), cy + dy * (dist - height)
    nx, ny = -dy, dx
    path = QPainterPath()
    path.moveTo(tip)
    path.lineTo(QPointF(bx + nx * half_base, by + ny * half_base))
    path.lineTo(QPointF(bx - nx * half_base, by - ny * half_base))
    path.closeSubpath()
    p.drawPath(path)


def _canvas(scale):
    px = QPixmap(int(SIZE * scale), int(SIZE * scale))
    px.setDevicePixelRatio(scale)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    return px, p


def _make_anchor(axes, scale):
    """The resting anchor: white disc, dark dot, one triangle per scrollable direction."""
    px, p = _canvas(scale)
    c = SIZE / 2
    p.setPen(QPen(QColor(30, 30, 30, 215), 1.0))
    p.setBrush(WHITE)
    p.drawEllipse(QPointF(c, c), 10.5, 10.5)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(DARK)
    p.drawEllipse(QPointF(c, c), 2.3, 2.3)
    dirs = []
    if "v" in axes:
        dirs += [(0, -1), (0, 1)]
    if "h" in axes:
        dirs += [(-1, 0), (1, 0)]
    for dx, dy in dirs:
        _tri(p, c, c, dx, dy, 8.0, 3.5, 3.3)
    p.end()
    return QCursor(px, int(c), int(c))


def _make_pan(direction, scale):
    """Moving: a small dot with a single outlined triangle pointing in the scroll direction."""
    px, p = _canvas(scale)
    c = SIZE / 2
    dx, dy = direction
    dot = QPointF(c - dx * 3.9, c - dy * 3.9)
    # white halo first, so the glyph reads on dark and light pages alike
    p.setPen(QPen(WHITE, 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(WHITE)
    p.drawEllipse(dot, 2.9, 2.9)
    _tri(p, c, c, dx, dy, 6.9, 3.9, 4.3)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(DARK)
    p.drawEllipse(dot, 2.6, 2.6)
    _tri(p, c, c, dx, dy, 6.9, 3.9, 4.3)
    p.end()
    return QCursor(px, int(c), int(c))


_cache = {}


def _scale():
    app = QApplication.instance()
    scr = app.primaryScreen() if app else None
    return max(1.0, scr.devicePixelRatio()) if scr else 1.0


def direction_for(delta, axes):
    """Unit direction for the pointer offset from the anchor, limited to the axes that can scroll; None inside the dead zone."""
    if delta is None or math.hypot(delta[0], delta[1]) <= DEAD_ZONE:
        return None
    dx, dy = delta
    if axes == "v":
        return (0, 1 if dy > 0 else -1)
    if axes == "h":
        return (1 if dx > 0 else -1, 0)
    octant = int(round(math.atan2(dy, dx) / (math.pi / 4))) % 8
    return ((1, 0), (0.7071, 0.7071), (0, 1), (-0.7071, 0.7071), (-1, 0), (-0.7071, -0.7071), (0, -1), (0.7071, -0.7071))[octant]


def cursor_for(axes, direction):
    """The cursor for these scrollable axes ("v", "h" or "vh") and direction (None = resting anchor)."""
    scale = _scale()
    key = (axes if direction is None else None, direction, scale)
    if key not in _cache:
        _cache[key] = _make_anchor(axes, scale) if direction is None else _make_pan(direction, scale)
    return _cache[key]


def parse_axes(raw):
    raw = (raw or "").strip()
    if "v" in raw and "h" in raw:
        return "vh"
    return "h" if raw == "h" else "v"


class PanCursorFilter(QObject):
    """Install on a QWebEngineView; it finds (and re-finds) the render widget that actually owns the cursor."""

    def __init__(self, view):
        super().__init__(view)
        self.view = view
        from . import enhance
        if not enhance.ENABLED:
            return                                      # inert: no filters installed
        self._armed = False
        self._origin = None
        self._axes = "v"
        self._last = None
        self._busy = False
        self._watched = set()
        view.installEventFilter(self)
        self.attach()

    def attach(self):
        """(Re)hook the view's render widgets; Qt WebEngine creates / replaces them lazily."""
        from . import enhance
        if not enhance.ENABLED:
            return
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
        self._last = None

    def _arm(self, ev, obj):
        self._armed = True
        self._origin = ev.globalPosition()
        self._axes = "v"
        self._last = None
        try:
            zoom = self.view.page().zoomFactor() or 1.0
            pos = ev.position()
            self.view.page().runJavaScript(_AXES_JS % (pos.x() / zoom, pos.y() / zoom), lambda r, o=obj: self._axes_ready(r, o))
        except Exception:
            pass

    def _axes_ready(self, raw, obj):
        if self._armed:
            self._axes = parse_axes(raw)
            self._apply(obj)

    def _delta(self):
        if self._origin is None:
            return None
        d = QCursor.pos()
        return (d.x() - self._origin.x(), d.y() - self._origin.y())

    def _apply(self, obj):
        """Set the right cursor for the pointer's current offset (only when it changed)."""
        if not self._armed or self._busy or not isinstance(obj, QWidget):
            return
        direction = direction_for(self._delta(), self._axes)
        key = (self._axes, direction)
        if key == self._last:
            return
        self._last = key
        self._busy = True
        try:
            obj.setCursor(cursor_for(self._axes, direction))
        finally:
            self._busy = False

    def eventFilter(self, obj, ev):
        t = ev.type()
        try:
            if t == QEvent.Type.ChildPolished and obj is self.view:
                child = ev.child()                      # polished = fully constructed (ChildAdded fires mid-construction)
                if child is not None and child.isWidgetType() and child not in self._watched:
                    child.installEventFilter(self)
                    self._watched.add(child)
            elif t == QEvent.Type.MouseButtonPress:
                if ev.button() == Qt.MouseButton.MiddleButton and not self._armed:
                    self._arm(ev, obj)
                else:                                   # any click ends auto-scroll
                    self.disarm()
            elif t == QEvent.Type.MouseButtonRelease:
                if ev.button() == Qt.MouseButton.MiddleButton and self._armed and self._origin is not None:
                    d = ev.globalPosition() - self._origin       # press-hold-drag-release (Chrome's "drag" mode) ends here
                    if math.hypot(d.x(), d.y()) > 14:
                        self.disarm()
            elif t in (QEvent.Type.KeyPress, QEvent.Type.FocusOut, QEvent.Type.Leave, QEvent.Type.Hide):
                self.disarm()
            elif t == QEvent.Type.MouseMove and self._armed:
                self._apply(obj)                        # follow the pointer even when Chromium does not change its cursor
            elif t == QEvent.Type.CursorChange and self._armed and not self._busy and obj.isWidgetType():
                if obj.cursor().shape() in _PAN_SHAPES:
                    self._last = None
                    self._apply(obj)
        except Exception:
            pass
        return False
