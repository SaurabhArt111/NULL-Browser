"""Small animated widgets: toolbar buttons that fade their hover background.

(A colour veil that faded over the page on every tab switch used to live here. It made every tab change flash, so it was removed.)"""
from PyQt6.QtCore import QEasingCurve, QRectF, Qt, QVariantAnimation
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QToolButton


class HoverToolButton(QToolButton):
    """QToolButton whose hover / pressed background eases in and out instead of snapping (like Chrome's toolbar).

    The stylesheet has `QToolButton[anim="true"]` rules that leave the background transparent, so only this
    class paints the hover colour. `colors` is a callable returning (hover, pressed) CSS colours so the button
    follows theme changes without being rebuilt. `radius=None` makes the background a circle / pill.
    """

    def __init__(self, colors, radius=None, parent=None):
        super().__init__(parent)
        from . import enhance
        self._on = enhance.ENABLED                      # classic mode: behave exactly like a plain QToolButton
        self._colors, self._radius = colors, radius
        self._t = 0.0
        self._forced = False
        self._anim = QVariantAnimation(self, duration=130, easingCurve=QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._set_t)
        if self._on:
            self.setProperty("anim", True)

    def _set_t(self, v):
        self._t = float(v)
        self.update()

    def _go(self, target):
        if not self._on:
            return
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
        if self._on and self.isEnabled() and (self._t > 0.001 or self.isDown()):
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
