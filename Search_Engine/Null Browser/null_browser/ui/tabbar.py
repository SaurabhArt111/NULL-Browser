"""Chrome-style tab strip: adaptive widths, pinned tabs, audio buttons, loading spinner, drag reorder."""
import logging

from PyQt6.QtCore import QEasingCurve, QElapsedTimer, QPoint, QPointF, QRectF, QSize, Qt, QTimer, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QCursor, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QHBoxLayout, QMenu, QTabBar, QWidget

from . import icons
from . import enhance
from .tips import tip
from .widgets import HoverToolButton

log = logging.getLogger("null.tabbar")


class TabStrip(QTabBar):
    """Chrome-style tab strip. Tabs are painted here (not by the style sheet) so that

    * the selected tab - and the tab being dragged - is always drawn last, i.e. on top of its neighbours and of their flares,
    * dragging follows the pointer pixel for pixel and the other tabs glide out of the way (no pixmap snapshot, no jumps),
    * close / audio buttons are part of the tab, so nothing paints over a neighbouring tab.
    """
    closeRequested = pyqtSignal(int)
    newTabRequested = pyqtSignal()
    menuAction = pyqtSignal(str, int)         # action name, tab index
    audioToggled = pyqtSignal(int)

    PINNED_W, MIN_W, MAX_W = 46, 40, 240
    TEAR = 14                                  # px beyond the strip before a drag turns into a new window
    reserved = 270                             # width taken by search / + / window buttons (set by the window)
    TOP, RADIUS, FLARE = 7, 10, 8              # gap above the tabs, corner radius, concave flare at the foot of the selected tab
    HALF_LIFE_MS = 55.0                        # how fast displaced tabs glide into place

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setExpanding(False)
        self.setMovable(False)                 # dragging is implemented below
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
        self._drag = None                      # active TabDrag (tear-off into another window)
        self._pending = None                   # ("close" | "audio" | "middle", index) waiting for the button to be released
        self._dix, self._dx, self._grab = -1, 0.0, 0     # in-strip drag: dragged index, its left edge, pointer offset inside it
        self._off = {}                         # tab id -> horizontal offset still to glide out (px)
        self._next_id = 1
        self._hover, self._hover_part = -1, ""
        self._loading = set()
        self._frames = []
        self._frame = 0
        self._timer = QTimer(self, interval=80)
        self._timer.timeout.connect(self._spin)
        self._glide = QTimer(self, interval=15)
        self._glide.timeout.connect(self._glide_step)
        self._clock = QElapsedTimer()
        self._grow_idx, self._grow_f = -1, 1.0                  # tab being animated open, and how far (0..1)
        if enhance.ENABLED:
            self._grow = QVariantAnimation(self, duration=170, easingCurve=QEasingCurve.Type.OutCubic)
            self._grow.valueChanged.connect(self._grow_step)
            self._grow.finished.connect(self._grow_done)
        self.restyle()

    def restyle(self):
        self._frames = icons.spinner_frames(self.app.accent)
        self.update()

    # -- per-tab state (kept in tabData so it moves with the tab) -----------------------------------------------
    def _meta(self, i):
        d = self.tabData(i)
        return d if isinstance(d, dict) else {}

    def _set_meta(self, i, **kw):
        d = dict(self._meta(i))
        d.update(kw)
        self.setTabData(i, d)

    def is_pinned(self, i):
        return bool(self._meta(i).get("pinned"))

    def _tab_id(self, i):
        d = self._meta(i)
        if "id" not in d:
            self._set_meta(i, id=self._next_id)
            self._next_id += 1
            d = self._meta(i)
        return d["id"]

    # -- sizing --------------------------------------------------------------------------
    def tabSizeHint(self, index):
        h = 40
        if self.is_pinned(index):
            return QSize(self.PINNED_W, h)
        n = self.count()
        pinned = sum(1 for i in range(n) if self.is_pinned(i))
        avail = max(200, (self.parentWidget().width() if self.parentWidget() else 1000) - self.reserved) - pinned * self.PINNED_W
        unpinned = max(1, n - pinned)
        w = max(self.MIN_W, min(self.MAX_W, avail // unpinned))
        if index == self._grow_idx and self._grow_f < 1.0:
            w = max(10, int(w * self._grow_f))
        return QSize(w, h)

    def tabInserted(self, index):
        super().tabInserted(index)
        self._set_meta(index, id=self._next_id)
        self._next_id += 1
        if enhance.ENABLED and self.isVisible() and self.count() > 1 and not self.is_pinned(index):   # new tabs slide open instead of popping in
            self._grow_idx, self._grow_f = index, 0.0
            self._grow.stop()
            self._grow.setStartValue(0.0)
            self._grow.setEndValue(1.0)
            self._grow.start()

    def tabRemoved(self, index):
        super().tabRemoved(index)
        if enhance.ENABLED:
            self._grow.stop()                                      # indexes shifted: settle immediately
        self._grow_idx, self._grow_f = -1, 1.0
        self._hover, self._hover_part = -1, ""

    def _grow_step(self, v):
        self._grow_f = float(v)
        i = self._grow_idx
        if 0 <= i < self.count():
            self.setTabText(i, self.tabText(i))               # makes QTabBar ask tabSizeHint again

    def _grow_done(self):
        i, self._grow_idx, self._grow_f = self._grow_idx, -1, 1.0
        if 0 <= i < self.count():
            self.setTabText(i, self.tabText(i))

    def minimumTabSizeHint(self, index):
        return QSize(self.PINNED_W if self.is_pinned(index) else self.MIN_W, 40)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.updateGeometry()

    # -- state set by the window ---------------------------------------------------------------
    def decorate(self, index, pinned, audible, muted):
        self._set_meta(index, pinned=bool(pinned), audible=bool(audible), muted=bool(muted))
        self.update()

    # -- geometry of the parts of a tab ---------------------------------------------------------
    def _body(self, i, rect=None):
        r = QRectF(rect if rect is not None else self.tabRect(i))
        return QRectF(r.left(), r.top() + self.TOP, r.width(), r.height() - self.TOP)

    def _parts(self, i, body, selected, hovered):
        """Rectangles inside a tab body: icon, audio button, close button and the text area. None = not shown."""
        pinned = self.is_pinned(i)
        m = self._meta(i)
        cy = body.center().y()
        if pinned:
            icon = QRectF(body.center().x() - 8, cy - 8, 16, 16)
            return {"icon": icon, "audio": None, "close": None, "text": None}
        icon = QRectF(body.left() + 12, cy - 8, 16, 16)
        right = body.right() - 6
        close = audio = None
        if selected or hovered or body.width() >= 104:
            close = QRectF(right - 20, cy - 10, 20, 20)
            right = close.left() - 2
        if (m.get("audible") or m.get("muted")) and body.width() >= 70:
            audio = QRectF(right - 20, cy - 10, 20, 20)
            right = audio.left() - 2
        text = QRectF(icon.right() + 8, body.top(), max(0.0, right - icon.right() - 10), body.height())
        if text.width() < 20:
            text = None
        return {"icon": icon, "audio": audio, "close": close, "text": text}

    def _hit(self, i, pos):
        body = self._body(i)
        parts = self._parts(i, body, i == self.currentIndex(), True)
        p = QPointF(pos)
        for name in ("close", "audio"):
            r = parts[name]
            if r is not None and r.contains(p):
                return name
        return ""

    # -- painting -------------------------------------------------------------------------------
    def _shape(self, body, flare):
        x0, y0, x1, y1 = body.left(), body.top(), body.right(), body.bottom()
        R, F = self.RADIUS, (self.FLARE if flare else 0)
        path = QPainterPath()
        path.moveTo(x0 - F, y1)
        if F:
            path.quadTo(x0, y1, x0, y1 - F)
        path.lineTo(x0, y0 + R)
        path.quadTo(x0, y0, x0 + R, y0)
        path.lineTo(x1 - R, y0)
        path.quadTo(x1, y0, x1, y0 + R)
        path.lineTo(x1, y1 - F)
        if F:
            path.quadTo(x1, y1, x1 + F, y1)
        path.closeSubpath()
        return path

    def _draw_rect(self, i):
        r = QRectF(self.tabRect(i))
        if i == self._dix:
            r.moveLeft(self._dx)
        else:
            r.translate(self._off.get(self._tab_id(i), 0.0), 0)
        return r

    def paintEvent(self, ev):
        n = self.count()
        if n == 0:
            return
        pal = self.app.pal
        cur = self.currentIndex()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        dragging = self._dix >= 0
        # separators first (they sit between tabs, under everything)
        if not dragging:
            sep = QColor(pal["muted"])
            sep.setAlphaF(0.35)
            p.setPen(QPen(sep, 1))
            for i in range(n - 1):
                if i in (cur, self._hover) or (i + 1) in (cur, self._hover):
                    continue
                r = self._draw_rect(i)
                x = round(r.right()) + 0.5
                p.drawLine(QPointF(x, r.top() + self.TOP + 9), QPointF(x, r.bottom() - 9))
        # z-order: ordinary tabs, then the selected one, then the one being dragged - always on top
        order = [i for i in range(n) if i != cur and i != self._dix]
        if 0 <= cur < n and cur != self._dix:
            order.append(cur)
        if self._dix >= 0:
            order.append(self._dix)
        for i in order:
            self._paint_tab(p, i, pal, selected=(i == cur), lifted=(i == self._dix))
        p.end()

    def _paint_tab(self, p, i, pal, selected, lifted):
        r = self._draw_rect(i)
        if r.right() < 0 or r.left() > self.width():
            return
        body = self._body(i, r)
        hovered = (i == self._hover) and self._dix < 0
        if selected:
            if lifted:                                                  # soft shadow so the lifted tab reads as above the others
                sh = QColor(0, 0, 0, 38)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(sh)
                p.drawPath(self._shape(body.translated(0, 1.5).adjusted(-1, 0, 1, 0), False))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(pal["bar"]))
            p.drawPath(self._shape(body, True))
        elif hovered:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(pal["tab_hover"]))
            p.drawPath(self._shape(body.adjusted(0, 0, 0, -1), False))
        parts = self._parts(i, body, selected, hovered)
        ic = self.tabIcon(i)
        if not ic.isNull():
            ic.paint(p, parts["icon"].toRect(), Qt.AlignmentFlag.AlignCenter)
        if parts["text"] is not None:
            p.setPen(QColor(pal["text"] if (selected or hovered or lifted) else pal["muted"]))
            p.setFont(self.font())
            text = QFontMetrics(self.font()).elidedText(self.tabText(i), Qt.TextElideMode.ElideRight, int(parts["text"].width()))
            p.drawText(parts["text"], int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), text)
        m = self._meta(i)
        for name, icon_name in (("audio", "mute" if m.get("muted") else "volume"), ("close", "close")):
            rr = parts[name]
            if rr is None:
                continue
            if i == self._hover and self._hover_part == name and self._dix < 0:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(pal["press"]))
                p.drawEllipse(rr)
            self.app.icon(icon_name, size=14).paint(p, rr.toRect(), Qt.AlignmentFlag.AlignCenter)

    # -- hover ---------------------------------------------------------------------------------------
    def _set_hover(self, i, part):
        if (i, part) != (self._hover, self._hover_part):
            self._hover, self._hover_part = i, part
            self.update()

    def leaveEvent(self, ev):
        self._set_hover(-1, "")
        super().leaveEvent(ev)

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

    # -- dragging (reorder inside the strip) --------------------------------------------------------------
    def _group_bounds(self, i):
        n = self.count()
        pinned = self.is_pinned(i)
        idx = [k for k in range(n) if self.is_pinned(k) == pinned]
        return self.tabRect(idx[0]).left(), self.tabRect(idx[-1]).right(), idx[0], idx[-1]

    def _begin_drag(self, idx):
        self._dix = idx
        self._dx = float(self.tabRect(idx).left())
        self.update()

    def _drag_to(self, mouse_x):
        i = self._dix
        lo, hi, first, last = self._group_bounds(i)
        w = self.tabRect(i).width()
        x = max(float(lo), min(float(hi - w), float(mouse_x - self._grab)))
        self._dx = x
        centre = x + w / 2.0
        while i < last and centre > self.tabRect(i + 1).center().x():
            self._swap(i, i + 1)
            i += 1
        while i > first and centre < self.tabRect(i - 1).center().x():
            self._swap(i, i - 1)
            i -= 1
        self._dix = i
        self.update()

    def _swap(self, a, b):
        """Move tab a to position b; the tab it jumps over keeps its old on-screen position and glides to the new one."""
        nid = self._tab_id(b)
        before = self.tabRect(b).left() + self._off.get(nid, 0.0)
        self.moveTab(a, b)                                          # emits tabMoved, the window reorders its pages
        after = self.tabRect(a).left()
        self._off[nid] = before - after
        self._start_glide()

    def _start_glide(self):
        if not self._glide.isActive():
            self._clock.start()
            self._glide.start()

    def _glide_step(self):
        dt = max(1, self._clock.restart())
        k = 0.5 ** (dt / self.HALF_LIFE_MS)
        alive = {self._tab_id(i) for i in range(self.count())}
        for key in list(self._off):
            v = self._off[key] * k
            if key not in alive or abs(v) < 0.4:
                del self._off[key]
            else:
                self._off[key] = v
        if not self._off:
            self._glide.stop()
        self.update()

    def _end_drag(self):
        if self._dix < 0:
            return
        i, self._dix = self._dix, -1
        self._off[self._tab_id(i)] = self._dx - self.tabRect(i).left()           # settle into the slot instead of snapping
        self._start_glide()
        self.update()

    def _cancel_drag(self):
        self._dix = -1
        self._off.clear()
        self.update()

    # -- input ----------------------------------------------------------------------------------------
    def mousePressEvent(self, ev):
        pos = ev.position().toPoint()
        i = self.tabAt(pos)
        if i < 0:
            ev.ignore()                                    # empty strip area drags the window
            return
        b = ev.button()
        if b == Qt.MouseButton.LeftButton:
            part = self._hit(i, pos)
            if part:
                self._pending = (part, i)
            else:
                if i != self.currentIndex():
                    self.setCurrentIndex(i)                # like Chrome: the tab is selected the moment it is pressed
                self._press = (i, pos, ev.globalPosition().toPoint())
                self._grab = pos.x() - self.tabRect(i).left()
            self._off.clear()
            ev.accept()
        elif b == Qt.MouseButton.MiddleButton:
            self._pending = ("middle", i)
            ev.accept()
        else:
            ev.accept()

    def mouseMoveEvent(self, ev):
        pos = ev.position().toPoint()
        if self._drag is not None:
            self._drag.move(ev.globalPosition().toPoint())
            return
        if self._press is None and self._dix < 0:
            i = self.tabAt(pos)
            self._set_hover(i, self._hit(i, pos) if i >= 0 else "")
        if self._press is not None and ev.buttons() & Qt.MouseButton.LeftButton:
            idx, ppos, gpos = self._press
            g = ev.globalPosition().toPoint()
            cur = self._dix if self._dix >= 0 else idx
            win = self.window()
            if self.count() == 1:
                far = (g - gpos).manhattanLength() > 6                     # the only tab: drag the whole window
            else:
                geo = win.frameGeometry()
                far = (pos.y() < -self.TEAR or pos.y() > self.height() + self.TEAR
                       or g.x() < geo.left() - 60 or g.x() > geo.right() + 60)
            if far:
                from .tabdrag import TabDrag
                self._cancel_drag()
                self._drag = TabDrag(self, cur, QPoint(int(ppos.x()), int(ppos.y())), g)
                self._press = None
                return
            if self._dix < 0 and abs(pos.x() - ppos.x()) > 4 and self.count() > 1:
                self._begin_drag(idx)
            if self._dix >= 0:
                self._drag_to(pos.x())

    def mouseReleaseEvent(self, ev):
        if self._drag is not None:
            drag, self._drag = self._drag, None
            drag.finish(ev.globalPosition().toPoint())
            return
        pos = ev.position().toPoint()
        self._press = None
        self._end_drag()
        pending, self._pending = self._pending, None
        if pending is not None:
            kind, i = pending
            if self.tabAt(pos) == i and 0 <= i < self.count():
                if kind == "middle" and ev.button() == Qt.MouseButton.MiddleButton:
                    self.closeRequested.emit(i)
                elif kind == "close" and self._hit(i, pos) == "close":
                    self.closeRequested.emit(i)
                elif kind == "audio" and self._hit(i, pos) == "audio":
                    self.audioToggled.emit(i)
        ev.accept()

    def finish_qt_drag(self, ev_pos, global_pos):
        """Kept for TabDrag: there is no Qt-owned drag to settle any more."""
        self._cancel_drag()

    def mouseDoubleClickEvent(self, ev):
        if self.tabAt(ev.position().toPoint()) < 0:
            ev.ignore()                                    # double-click on empty strip toggles maximise (handled by the strip)
        else:
            ev.accept()

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
            add("Unpin tab" if self.is_pinned(i) else "Pin tab", "pin", "pin")
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
        colors = lambda: (win.pal["hover"], win.pal["press"])
        self.min_btn = HoverToolButton(colors, radius=0)
        self.max_btn = HoverToolButton(colors, radius=0)
        self.close_btn = HoverToolButton(lambda: ("#e81123", "#f1707a"), radius=0)
        self._poll = QTimer(self, interval=40)                  # clears the hot look once Windows stops reporting the mouse
        self._poll.timeout.connect(self._poll_max)
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

    def set_max_state(self, hot=None, pressed=None):
        """The maximise button's mouse input is owned by Windows (snap layouts), so its look is driven from here."""
        if hot is not None:
            self.max_btn.set_forced(hot)
            if hot and not self._poll.isActive():
                self._poll.start()
            elif not hot:
                self._poll.stop()
        if pressed is not None:
            self.max_btn.setDown(pressed)

    def _poll_max(self):
        b = self.max_btn
        if not b.rect().contains(b.mapFromGlobal(QCursor.pos())):
            self._poll.stop()
            b.setDown(False)
            b.set_forced(False)

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
