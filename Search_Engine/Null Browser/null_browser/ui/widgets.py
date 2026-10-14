"""Small animated widgets: toolbar buttons that fade their hover background, and a veil that fades between pages."""
from PyQt6.QtCore import QEasingCurve, QRectF, Qt, QVariantAnimation
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QToolButton, QWidget


class HoverToolButton(QToolButton):
    """QToolButton whose hover / pressed background eases in and out instead of snapping (like Chrome's toolbar).

    The stylesheet has `QToolButton[anim="true"]` rules that leave the background transparent, so only this
    class paints the hover colour. `colors` is a callable returning (hover, pressed) CSS colours so the button
    follows theme changes without being rebuilt. `radius=None` makes the background a circle / pill.
    """

    def __init__(self, colors, radius=None, parent=None):
        super().__init__(parent)
        self._colors, self._radius = colors, radius
        self._t = 0.0
        self._forced = False
        self._anim = QVariantAnimation(self, duration=130, easingCurve=QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._set_t)
        self.setProperty("anim", True)

    def _set_t(self, v):
        self._t = float(v)
        self.update()

    def _go(self, target):
        self._anim.stop()
        self._anim.setStartValue(self._t)
        self._anim.setEndValue(float(target))
        self._anim.setDuration(130 if target else 190)
        self._anim.start()

    def set_forced(self, on):
        """Keep the hover look on while Windows owns the mouse (the maximise button's snap-layouts hit area)."""
        self._forced = bool(on)
        self._go(1 if (self._forced or self.underMouse()) else 0)

    def enterEvent(self, ev):
        self._go(1)
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        if not self._forced:
            self._go(0)
        super().leaveEvent(ev)

    def paintEvent(self, ev):
        if self.isEnabled() and (self._t > 0.001 or self.isDown()):
            hover, press = self._colors()
            col = QColor(press if self.isDown() else hover)
            if not self.isDown():
                col.setAlphaF(col.alphaF() * self._t)
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            r = QRectF(self.rect())
            rad = min(r.width(), r.height()) / 2 if self._radius is None else self._radius
            p.drawRoundedRect(r, rad, rad)
            p.end()
        super().paintEvent(ev)


class FadeVeil(QWidget):
    """A flat colour that sits over the page area and fades away: smooths tab switches and hides the blank frame
    Chromium shows before it has painted a new page."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._color = QColor("#000000")
        self._alpha = 0.0
        self._anim = QVariantAnimation(self, duration=170, easingCurve=QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._tick)
        self._anim.finished.connect(self.hide)
        self.hide()

    def _tick(self, v):
        self._alpha = float(v)
        self.update()

    def flash(self, color, start=0.85):
        if not self.parentWidget() or not self.parentWidget().isVisible():
            return
        self._color = QColor(color)
        self.setGeometry(self.parentWidget().rect())
        self._anim.stop()
        self._anim.setStartValue(start)
        self._anim.setEndValue(0.0)
        self._alpha = start
        self.show()
        self.raise_()
        self._anim.start()

    def paintEvent(self, ev):
        if self._alpha <= 0.001:
            return
        c = QColor(self._color)
        c.setAlphaF(self._alpha)
        p = QPainter(self)
        p.fillRect(self.rect(), c)
        p.end()
