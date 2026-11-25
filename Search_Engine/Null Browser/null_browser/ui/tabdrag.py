"""Chrome-style tab tear-off: drag a tab out of the strip to give it its own window, drag it over another window's
strip to merge it back. The source TabStrip keeps receiving the mouse (implicit grab) so it drives the whole gesture."""
import logging

from PyQt6.QtCore import QEasingCurve, QPoint, QRect, QVariantAnimation
from PyQt6.QtWidgets import QApplication

from . import enhance

log = logging.getLogger("null.tabdrag")


def fade(win, to, ms=140):
    """Ease a window's opacity to `to` (one animation per window; a new fade replaces the running one)."""
    old = getattr(win, "_fade_anim", None)
    if old is not None:
        old.stop()
    if not enhance.ENABLED:
        win.setWindowOpacity(to)
        return
    a = QVariantAnimation(win, duration=ms, easingCurve=QEasingCurve.Type.OutCubic)
    a.setStartValue(float(win.windowOpacity()))
    a.setEndValue(float(to))
    a.valueChanged.connect(lambda v, w=win: w.setWindowOpacity(float(v)))
    win._fade_anim = a
    a.start()


class TabDrag:
    def __init__(self, strip, index, local_pos, global_pos):
        self.strip = strip
        self.src = strip.window()
        self.app = self.src.app
        self.target = None
        self.solo = strip.count() == 1
        strip.finish_qt_drag(local_pos, global_pos)             # settle QTabBar's own reorder drag first
        rect = strip.tabRect(index)
        self.tab = self.src.tabs[index]
        dx = max(12, min(local_pos.x() - rect.left(), max(12, rect.width() - 12)))
        if self.solo:
            self.dst = self.src
            if self.src.isMaximized():                           # like Chrome: un-maximise under the cursor
                ratio = global_pos.x() / max(1, self.src.width())
                self.src.showNormal()
                QApplication.processEvents()
                self.off = QPoint(int(ratio * self.src.width()), max(10, local_pos.y() + self.src.contentsMargins().top()))
                self.src.move(global_pos - self.off)
            else:
                self.off = global_pos - self.src.frameGeometry().topLeft()
        else:
            size = self.src.normalGeometry().size() if self.src.isMaximized() else self.src.size()
            tab = self.src.detach_tab(index)
            dst = self.app.new_window(private=self.src.private, show=False, empty=True)
            dst._start_maximized = False
            dst.resize(size)
            dst.adopt_tab(tab)
            # The new window appears already under the pointer and fades in: it is shown fully transparent, placed, then
            # faded (it used to pop up at its default place for a frame and then jump to the pointer).
            dst.setWindowOpacity(0.0)
            dst.show()
            dst.layout().activate()
            r = dst.tabbar.tabRect(0)
            inside = dst.tabbar.mapTo(dst, QPoint(r.left() + dx, r.height() // 2))
            self.off = inside
            dst.move(global_pos - inside)
            dst.raise_()
            fade(dst, 1.0, 160)
            self.dst = dst

    def move(self, global_pos):
        try:
            self.dst.move(global_pos - self.off)
            self._hover(global_pos)
        except RuntimeError:
            pass                                                 # window already gone

    def _hover(self, global_pos):
        target = None
        for w in self.app.windows:
            if w is self.dst or w.private != self.dst.private or not w.isVisible() or w.isMinimized():
                continue
            top_left = w.strip.mapToGlobal(QPoint(0, 0))
            if QRect(top_left, w.strip.size()).adjusted(0, -8, 0, 8).contains(global_pos):
                target = w
                break
        if target is not self.target:
            if self.target is not None:
                self.target.clear_drop_hint()
            self.target = target
            fade(self.dst, 0.55 if target else 1.0, 120)
        if target is not None:
            target.show_drop_hint(global_pos)

    def finish(self, global_pos):
        dst, target = self.dst, self.target
        try:
            fade(dst, 1.0, 1)
            dst.setWindowOpacity(1.0)
            if target is not None:
                idx = target.drop_hint_index(global_pos)
                target.clear_drop_hint()
                tab = dst.detach_tab(dst.index_of(self.tab))
                target.adopt_tab(tab, idx)
                target.raise_()
                target.activateWindow()
                if not dst.tabs:
                    dst.close()
            else:
                dst.raise_()
                dst.activateWindow()
        except Exception:
            log.exception("finishing tab drag")
