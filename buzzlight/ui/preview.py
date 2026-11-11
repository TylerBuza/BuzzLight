"""Live picture of the monitor with its LEDs around it."""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from buzzlight.layout import Layout
from buzzlight.ui import theme


class StripPreview(QWidget):
    """Draws the screen and one dot per LED, colored with the latest frame.
    With `show_order`, numbers the first LEDs and draws the strip's start."""

    def __init__(self, parent=None, show_order: bool = False):
        super().__init__(parent)
        self.layout_ = Layout()
        self.frame: list[tuple[int, int, int]] | None = None
        self.show_order = show_order
        self.aspect = 21 / 9
        self.setMinimumHeight(170)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_layout(self, layout: Layout) -> None:
        self.layout_ = layout
        self.update()

    def set_frame(self, frame) -> None:
        self.frame = frame
        self.update()

    def set_aspect(self, w: int, h: int) -> None:
        if w > 0 and h > 0:
            self.aspect = w / h
            self.update()

    def _screen_rect(self) -> QRectF:
        m = 38.0 if self.show_order else 26.0
        w, h = self.width() - 2 * m, self.height() - 2 * m
        if w / max(h, 1) > self.aspect:
            w = h * self.aspect
        else:
            h = w / self.aspect
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def _point(self, r: QRectF, side: str, u: float, out: float) -> QPointF:
        if side == "top":
            return QPointF(r.left() + u * r.width(), r.top() - out)
        if side == "bottom":
            return QPointF(r.left() + u * r.width(), r.bottom() + out)
        if side == "left":
            return QPointF(r.left() - out, r.top() + u * r.height())
        return QPointF(r.right() + out, r.top() + u * r.height())

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self._screen_rect()
        leds = self.layout_.leds()
        frame = self.frame

        # glow behind the screen, from the LED colors
        if frame:
            for led in leds:
                c = frame[led.index]
                if max(c) < 8:
                    continue
                col = QColor(*c, 70)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(col)
                p.drawEllipse(self._point(r, led.side, led.u, 10), 14, 14)

        p.setPen(QPen(QColor(theme.BORDER), 2))
        p.setBrush(QColor("#0c0d10"))
        p.drawRoundedRect(r, 6, 6)

        dot = max(3.0, min(6.0, min(r.width(), r.height()) / 60))
        for led in leds:
            c = frame[led.index] if frame else (90, 96, 108)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(*c))
            p.drawEllipse(self._point(r, led.side, led.u, 12), dot, dot)

        if self.show_order and leds:
            f = QFont(self.font())
            f.setPointSizeF(7.5)
            p.setFont(f)
            p.setPen(QColor(theme.TEXT))
            for n, led in enumerate(leds[:3]):
                pt = self._point(r, led.side, led.u, 24)
                p.drawText(QRectF(pt.x() - 10, pt.y() - 8, 20, 16),
                           Qt.AlignmentFlag.AlignCenter, str(n + 1))
            start = self._point(r, leds[0].side, leds[0].u, 12)
            p.setPen(QPen(QColor(theme.ACCENT), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(start, dot + 4, dot + 4)
        p.end()
