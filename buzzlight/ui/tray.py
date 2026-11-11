"""System tray icon and menu."""

from __future__ import annotations

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from buzzlight import autostart
from buzzlight.ui import theme


class Tray:
    def __init__(self, window, controller, app):
        self.w = window
        self.c = controller
        self.app = app
        self._hinted = False

        self.icon = QSystemTrayIcon(theme.app_icon(), window)
        self.icon.setToolTip("BuzzLight")
        m = QMenu(window)

        self.act_show = m.addAction("Open BuzzLight")
        self.act_show.triggered.connect(self.show_window)
        m.addSeparator()
        self.act_power = m.addAction("Lights on")
        self.act_power.setCheckable(True)
        self.act_power.triggered.connect(self._power)
        self.act_amb = m.addAction("Ambilight")
        self.act_amb.setCheckable(True)
        self.act_amb.triggered.connect(self._ambilight)
        self.act_color = m.addAction("Solid color")
        self.act_color.setCheckable(True)
        self.act_color.triggered.connect(self._color)
        m.addSeparator()
        self.act_auto = QAction("Start with Windows", m)
        self.act_auto.setCheckable(True)
        self.act_auto.setEnabled(autostart.supported())
        self.act_auto.triggered.connect(self._autostart)
        m.addAction(self.act_auto)
        m.addSeparator()
        m.addAction("Quit").triggered.connect(self.quit)

        m.aboutToShow.connect(self.sync)
        self.menu = m
        self.icon.setContextMenu(m)
        self.icon.activated.connect(self._activated)
        self.icon.show()
        autostart.repair()

    @staticmethod
    def available() -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    def sync(self):
        s = self.c.settings
        self.act_power.setChecked(s.power)
        self.act_amb.setChecked(s.power and s.mode == "ambilight")
        self.act_color.setChecked(s.power and s.mode == "color")
        self.act_auto.setChecked(autostart.enabled())

    def set_connected(self, connected: bool, port):
        self.icon.setToolTip(f"BuzzLight — connected ({port})" if connected
                             else "BuzzLight — looking for the LED strip")

    def show_window(self):
        if self.w.isMinimized():
            self.w.showNormal()
        self.w.show()
        self.w.raise_()
        self.w.activateWindow()

    def _activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            if self.w.isVisible() and not self.w.isMinimized():
                self.w.hide()
            else:
                self.show_window()

    def _power(self, on):
        self.c.set_power(on)
        self.w.refresh()

    def _ambilight(self, on):
        self.c.set_mode("ambilight" if on else "color")
        self.w.refresh()

    def _color(self, _):
        self.c.set_mode("color")
        self.w.refresh()

    def _autostart(self, on):
        try:
            autostart.set_enabled(on)
        except OSError as e:
            self.icon.showMessage("BuzzLight", f"Couldn't change startup: {e}",
                                  QSystemTrayIcon.MessageIcon.Warning)
        self.w.refresh()

    def hint_once(self):
        if self._hinted:
            return
        self._hinted = True
        self.icon.showMessage("BuzzLight is still running",
                              "The lights keep going in the background. "
                              "Right-click the tray icon to quit.",
                              QSystemTrayIcon.MessageIcon.Information, 4000)

    def quit(self):
        self.w.request_quit()
        self.icon.hide()
        self.app.quit()
