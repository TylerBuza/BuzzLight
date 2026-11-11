"""Look & feel: palette, stylesheet, and the app icon (drawn in code)."""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (QBrush, QColor, QConicalGradient, QIcon, QPainter,
                         QPainterPath, QPen, QPixmap, QRadialGradient)

BG = "#121418"
SURFACE = "#1b1e24"
SURFACE_2 = "#242830"
BORDER = "#2f343d"
TEXT = "#e8eaee"
MUTED = "#8b919c"
ACCENT = "#ffb020"       # honey
ACCENT_2 = "#ff6a3d"
GOOD = "#3ecf8e"
BAD = "#ff5c5c"

STYLESHEET = f"""
* {{ font-family: "Segoe UI Variable", "Segoe UI", sans-serif; font-size: 10pt; }}
QWidget {{ background: {BG}; color: {TEXT}; }}
QLabel#Title {{ font-size: 15pt; font-weight: 600; }}
QLabel#Muted, QLabel[muted="true"] {{ color: {MUTED}; }}
QLabel#Section {{ color: {MUTED}; font-size: 9pt; font-weight: 600;
                  letter-spacing: 0.5px; text-transform: uppercase; }}
QFrame#Card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; }}
QFrame#Card QLabel, QFrame#Card QCheckBox, QFrame#Card QSlider,
QFrame#Card StripPreview, QFrame#Card LabeledSlider {{ background: transparent; }}
QColorDialog, QColorDialog QWidget {{ background: transparent; }}
QColorDialog QSpinBox, QColorDialog QLineEdit {{ background: {SURFACE_2}; }}
QColorDialog QPushButton {{ background: {SURFACE_2}; }}

QPushButton {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 8px;
               padding: 7px 14px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:pressed {{ background: {BORDER}; }}
QPushButton:disabled {{ color: {MUTED}; border-color: {SURFACE_2}; }}
QPushButton#Primary {{ background: {ACCENT}; color: #1a1305; border: none; font-weight: 600; }}
QPushButton#Primary:hover {{ background: #ffc24d; }}
QPushButton#Power {{ border-radius: 18px; min-width: 36px; max-width: 36px;
                     min-height: 36px; max-height: 36px; padding: 0; font-size: 13pt; }}
QPushButton#Power[on="true"] {{ background: {ACCENT}; color: #1a1305; border: none; }}

QPushButton#Nav {{ background: transparent; border: none; border-radius: 8px;
                   padding: 9px 14px; text-align: left; color: {MUTED}; }}
QPushButton#Nav:hover {{ color: {TEXT}; background: {SURFACE}; }}
QPushButton#Nav:checked {{ color: {TEXT}; background: {SURFACE_2}; }}

QSlider::groove:horizontal {{ height: 6px; background: {SURFACE_2}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {TEXT}; width: 16px; height: 16px;
                              margin: -5px 0; border-radius: 8px; }}

QComboBox, QSpinBox, QLineEdit {{ background: {SURFACE_2}; border: 1px solid {BORDER};
    border-radius: 8px; padding: 5px 8px; min-height: 20px; }}
QComboBox:hover, QSpinBox:hover, QLineEdit:hover {{ border-color: {ACCENT}; }}
QComboBox QAbstractItemView {{ background: {SURFACE}; border: 1px solid {BORDER};
    selection-background-color: {SURFACE_2}; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 34px; height: 18px; border-radius: 9px;
                        background: {SURFACE_2}; border: 1px solid {BORDER}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QToolTip {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER}; padding: 6px; }}
"""


def make_icon_pixmap(size: int = 256) -> QPixmap:
    """BuzzLight mark: a glowing ring of honey→coral light around a dark
    screen. Drawn in code so the app ships no third-party art."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)
    c = QPointF(s / 2, s / 2)

    glow = QRadialGradient(c, s / 2)
    glow.setColorAt(0.55, QColor(255, 160, 40, 150))
    glow.setColorAt(1.0, QColor(255, 106, 61, 0))
    p.setBrush(QBrush(glow))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(c, s / 2, s / 2)

    ring = QConicalGradient(c, 90)
    for pos, col in ((0.0, "#ffb020"), (0.33, "#ff6a3d"), (0.66, "#ff3d8b"), (1.0, "#ffb020")):
        ring.setColorAt(pos, QColor(col))
    p.setPen(QPen(QBrush(ring), s * 0.09))
    p.setBrush(Qt.BrushStyle.NoBrush)
    inset = s * 0.2
    p.drawRoundedRect(QRectF(inset, inset * 1.25, s - 2 * inset, s - 2.5 * inset), s * 0.08, s * 0.08)

    screen = QPainterPath()
    inner = s * 0.27
    screen.addRoundedRect(QRectF(inner, inner * 1.17, s - 2 * inner, s - 2.34 * inner), s * 0.04, s * 0.04)
    p.fillPath(screen, QColor("#15171c"))
    p.end()
    return pm


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(make_icon_pixmap(size))
    return icon
