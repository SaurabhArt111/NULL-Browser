"""Chrome-style tab strip: adaptive widths, pinned tabs, audio buttons, loading spinner, drag reorder."""
import logging

from PyQt6.QtCore import QEasingCurve, QElapsedTimer, QPoint, QPointF, QRectF, QSize, Qt, QTimer, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QCursor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QAbstractButton, QHBoxLayout, QMenu, QTabBar, QWidget

from . import icons
from . import enhance
from .tips import tip

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
        self._frozen_w = None                  # after closing a tab with the mouse, widths stay put until the pointer leaves (Chrome)
        self._pinned_n = None                  # cached number of pinned tabs (tabSizeHint is called once per tab per layout)
        self._fm = None
        self._frames = []
        self._frame = 0
        self._timer = QTimer(self, interval=40)                 # 24 frames x 40 ms = one turn per second (cheap: only the icons repaint)
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
        self._frames = icons.spinner_frames(self.app.accent, steps=24)
        self._fm = None
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
    def _pinned_count(self):
        if self._pinned_n is None:
            self._pinned_n = sum(1 for i in range(self.count()) if self.is_pinned(i))
        return self._pinned_n

    def tabSizeHint(self, index):
        h = 40
        if self.is_pinned(index):
            return QSize(self.PINNED_W, h)
        n = self.count()
        pinned = self._pinned_count()
        avail = max(200, (self.parentWidget().width() if self.parentWidget() else 1000) - self.reserved) - pinned * self.PINNED_W
        unpinned = max(1, n - pinned)
        w = max(self.MIN_W, min(self.MAX_W, avail // unpinned))
        if self._frozen_w is not None:
            w = min(self.MAX_W, self._frozen_w)
        if index == self._grow_idx and self._grow_f < 1.0:
            w = max(10, int(w * self._grow_f))
        return QSize(w, h)

    def tabInserted(self, index):
        self._pinned_n = None
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
        self._pinned_n = None
        super().tabRemoved(index)
        self._sync_spinner()
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
        old = self._meta(index)
        if (old.get("pinned"), old.get("audible"), old.get("muted")) == (bool(pinned), bool(audible), bool(muted)):
            return                                                 # nothing changed: no repaint (audio signals fire often)
        pin_changed = bool(old.get("pinned")) != bool(pinned)
        self._set_meta(index, pinned=bool(pinned), audible=bool(audible), muted=bool(muted))
        if pin_changed:
            self._pinned_n = None
            self.setTabText(index, self.tabText(index))           # width changes: relayout once
        self.update(self.tabRect(index).adjusted(-self.FLARE, 0, self.FLARE, 0))

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
        m = self._meta(i)
        if m.get("loading") and self._frames:                         # spinner is painted, not set as the tab icon (no relayout per frame)
            self._frames[self._frame % len(self._frames)].paint(p, parts["icon"].toRect(), Qt.AlignmentFlag.AlignCenter)
        else:
            ic = self.tabIcon(i)
            if not ic.isNull():
                ic.paint(p, parts["icon"].toRect(), Qt.AlignmentFlag.AlignCenter)
        if parts["text"] is not None:
            p.setPen(QColor(pal["text"] if (selected or hovered or lifted) else pal["muted"]))
            p.setFont(self.font())
            if self._fm is None:
                self._fm = QFontMetrics(self.font())
            text = self._fm.elidedText(self.tabText(i), Qt.TextElideMode.ElideRight, int(parts["text"].width()))
            p.drawText(parts["text"], int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), text)
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
        self._unfreeze()
        super().leaveEvent(ev)

    def _freeze_widths(self, i):
        """Closing tabs one after another with the mouse: keep the remaining tabs' width so the next close button slides
        under the pointer instead of the strip re-flowing (Chrome). Released when the pointer leaves the strip."""
        if 0 <= i < self.count() and not self.is_pinned(i) and i < self.count() - 1:
            self._frozen_w = self.tabRect(i).width()

    def _unfreeze(self):
        if self._frozen_w is not None:
            self._frozen_w = None
            if self.count():
                self.setTabText(0, self.tabText(0))          # re-layout once with the normal widths

    # -- loading spinner ---------------------------------------------------------------------------
    # The loading state lives in tabData, so it follows the tab when tabs are moved, dragged or closed.
    def set_loading(self, index, loading):
        if not (0 <= index < self.count()) or bool(self._meta(index).get("loading")) == bool(loading):
            return
        self._set_meta(index, loading=bool(loading))
        self.update(self.tabRect(index))
        self._sync_spinner()

    def clear_loading(self):
        for i in range(self.count()):
            if self._meta(i).get("loading"):
                self._set_meta(i, loading=False)
        self._sync_spinner()

    def _loading_indexes(self):
        return [i for i in range(self.count()) if self._meta(i).get("loading")]

    def _sync_spinner(self):
        busy = bool(self._loading_indexes())
        if busy and not self._timer.isActive():
            self._timer.start()
        elif not busy and self._timer.isActive():
            self._timer.stop()

    def _spin(self):
        if not self._frames:
            return
        self._frame = (self._frame + 1) % len(self._frames)
        idx = self._loading_indexes()
        if not idx:
            self._timer.stop()
            return
        for i in idx:                                               # repaint only the icons that spin
            r = self._draw_rect(i)
            self.update(int(r.left()) + 8, 0, 28, self.height())

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
            ev.ignore()                                    # empty strip area drags the window / middle-click opens a tab
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
                    self._freeze_widths(i)
                    self.closeRequested.emit(i)
                elif kind == "close" and self._hit(i, pos) == "close":
                    self._freeze_widths(i)
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
        add("Reopen closed tab", "reopen", "history", bool(getattr(self.app.app, "closed", None)))
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
        if ev.button() == Qt.MouseButton.MiddleButton:
            ev.accept()                                    # handled on release
            return
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
        if ev.button() == Qt.MouseButton.MiddleButton and self.rect().contains(ev.position().toPoint()):
            self.win.new_tab()                             # middle-click on empty tab-strip space: new tab
            ev.accept()
            return
        super().mouseReleaseEvent(ev)

    def mouseDoubleClickEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._manual = None
            self.win.toggle_maximized()
            ev.accept()
            return
        super().mouseDoubleClickEvent(ev)


class CaptionButton(QAbstractButton):
    """A Windows-11-style caption button (minimise / maximise / restore / close).

    The glyph is the system's own (Segoe Fluent Icons on Windows 11, Segoe MDL2 Assets on Windows 10) so it is pixel-identical
    to every other window; elsewhere a crisp 10 px vector glyph aligned to device pixels is drawn instead. Hover fades in /
    out like Windows does, close turns red with a white glyph, and the glyph dims while the window is inactive."""
    GLYPHS = {"minimize": "\ue921", "maximize": "\ue922", "restore": "\ue923", "close": "\ue8bb"}
    W, H = 46, 32                                         # Windows 11 caption button size (logical px)
    _font_family = None

    def __init__(self, kind, win, parent=None):
        super().__init__(parent)
        self.kind, self.win = kind, win
        self._t = 0.0
        self._forced = False
        self.setFixedSize(self.W, self.H)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._anim = QVariantAnimation(self, duration=110, easingCurve=QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(lambda v: (setattr(self, "_t", float(v)), self.update()))

    @classmethod
    def font_family(cls):
        if cls._font_family is None:
            from PyQt6.QtGui import QFontDatabase
            fams = set(QFontDatabase.families())
            cls._font_family = next((f for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets") if f in fams), "")
        return cls._font_family

    def set_kind(self, kind):
        if kind != self.kind:
            self.kind = kind
            self.update()

    def _go(self, target):
        if not enhance.ENABLED:
            self._t = float(target)
            self.update()
            return
        self._anim.stop()
        self._anim.setStartValue(self._t)
        self._anim.setEndValue(float(target))
        self._anim.setDuration(90 if target else 160)
        self._anim.start()

    def set_forced(self, on):
        """Keep the hover look while Windows owns the mouse (the maximise button's Snap Layouts area)."""
        self._forced = bool(on)
        self._go(1 if (self._forced or self.underMouse()) else 0)

    def enterEvent(self, ev):
        self._go(1)
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        if not self._forced:
            self._go(0)
        super().leaveEvent(ev)

    def sizeHint(self):
        return QSize(self.W, self.H)

    def paintEvent(self, ev):
        pal = self.win.pal
        dark = bool(pal.get("dark"))
        close = self.kind == "close"
        down = self.isDown()
        p = QPainter(self)
        if self._t > 0.001 or down:
            if close:
                bg = QColor("#c42b1c") if not down else QColor(200, 64, 50)
            else:
                bg = QColor(255, 255, 255, 18 if not down else 11) if dark else QColor(0, 0, 0, 15 if not down else 9)
            if not down:
                bg.setAlphaF(bg.alphaF() * self._t)
            p.fillRect(self.rect(), bg)
        fg = QColor(pal["text"])
        if close and (self._t > 0.5 or down):
            fg = QColor("#ffffff")
        elif not self.window().isActiveWindow():
            fg.setAlphaF(0.45)                                # Windows dims caption glyphs of inactive windows
        fam = self.font_family()
        if fam:
            f = QFont(fam)
            f.setPixelSize(10)
            p.setFont(f)
            p.setPen(fg)
            p.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), self.GLYPHS[self.kind])
        else:
            self._draw_vector(p, fg)
        p.end()

    def _draw_vector(self, p, fg):
        dpr = self.devicePixelRatioF()
        px = 1.0 / dpr                                        # one device pixel
        pen = QPen(fg, max(1.0, round(dpr)) / dpr)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        cx, cy, s = self.width() / 2, self.height() / 2, 10.0
        snap = lambda v: round(v * dpr) / dpr + px / 2        # centre a 1-device-pixel line on a pixel
        x0, y0 = snap(cx - s / 2), snap(cy - s / 2)
        if self.kind == "minimize":
            p.drawLine(QPointF(x0, snap(cy)), QPointF(x0 + s, snap(cy)))
        elif self.kind == "maximize":
            p.drawRect(QRectF(x0, y0, s - px, s - px))
        elif self.kind == "restore":
            o = 2.0
            p.drawRect(QRectF(x0, y0 + o, s - o - px, s - o - px))
            p.drawPolyline([QPointF(x0 + o, y0 + o), QPointF(x0 + o, y0), QPointF(x0 + s - px, y0),
                            QPointF(x0 + s - px, y0 + s - o - px), QPointF(x0 + s - o - px, y0 + s - o - px)])
        else:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.drawLine(QPointF(cx - s / 2, cy - s / 2), QPointF(cx + s / 2, cy + s / 2))
            p.drawLine(QPointF(cx + s / 2, cy - s / 2), QPointF(cx - s / 2, cy + s / 2))


class WindowControls(QWidget):
    """[ - ][ □ ][ x ] flush with the top-right corner, sized and drawn like Windows 11's own caption buttons."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setObjectName("wincontrols")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.min_btn = CaptionButton("minimize", win)
        self.max_btn = CaptionButton("maximize", win)
        self.close_btn = CaptionButton("close", win)
        self._poll = QTimer(self, interval=40)                  # clears the hot look once Windows stops reporting the mouse
        self._poll.timeout.connect(self._poll_max)
        for b, name, fn in ((self.min_btn, "wc_min", win.showMinimized), (self.max_btn, "wc_max", win.toggle_maximized),
                            (self.close_btn, "wc_close", win.close)):
            b.setObjectName(name)
            b.clicked.connect(lambda _=False, f=fn: f())
            lay.addWidget(b)
        tip(self.min_btn, "Minimize", "Send this window to the taskbar")
        tip(self.close_btn, "Close", "Close every tab in this window", "Alt+F4")
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

    def changeEvent(self, ev):
        super().changeEvent(ev)
        if ev.type() == ev.Type.ActivationChange:
            for b in (self.min_btn, self.max_btn, self.close_btn):
                b.update()

    def refresh(self):
        maxed = self.win.isMaximized()
        self.max_btn.set_kind("restore" if maxed else "maximize")
        for b in (self.min_btn, self.max_btn, self.close_btn):
            b.update()
        tip(self.max_btn, "Restore down" if maxed else "Maximize", "Return the window to its previous size" if maxed else "Fill the whole screen", "Double-click the title bar")
