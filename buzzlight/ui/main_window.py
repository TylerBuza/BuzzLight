"""BuzzLight main window."""

from __future__ import annotations

from PyQt6.QtCore import QObject, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices
from PyQt6.QtWidgets import (QButtonGroup, QCheckBox, QColorDialog, QComboBox,
                             QFrame, QGridLayout, QHBoxLayout, QLabel,
                             QMainWindow, QMessageBox, QPushButton, QSlider,
                             QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

from buzzlight import __version__, autostart
from buzzlight.ambilight.capture import list_monitors
from buzzlight.controller import Controller
from buzzlight.device.protocol import LED_COUNT
from buzzlight.layout import CORNERS, Layout
from buzzlight.paths import config_dir
from buzzlight.ui import theme
from buzzlight.ui.preview import StripPreview

PRESETS = [
    ("Warm white", (255, 170, 90)), ("Daylight", (255, 230, 200)),
    ("Honey", (255, 150, 20)), ("Coral", (255, 80, 50)),
    ("Rose", (255, 40, 120)), ("Violet", (150, 60, 255)),
    ("Ocean", (20, 110, 255)), ("Teal", (0, 210, 170)),
    ("Lime", (120, 255, 40)), ("Red", (255, 0, 0)),
]


class _Bridge(QObject):
    """Carries callbacks from worker threads onto the GUI thread."""
    status = pyqtSignal(bool, object)


def card(*widgets, spacing=10) -> QFrame:
    f = QFrame()
    f.setObjectName("Card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(16, 14, 16, 16)
    lay.setSpacing(spacing)
    for w in widgets:
        if isinstance(w, QWidget):
            lay.addWidget(w)
        else:
            lay.addLayout(w)
    return f


def section(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setObjectName("Section")
    return lbl


def muted(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("Muted")
    lbl.setWordWrap(True)
    return lbl


class LabeledSlider(QWidget):
    """Slider with a name on the left and a formatted value on the right."""

    def __init__(self, name, lo, hi, value, fmt, on_change, tip=""):
        super().__init__()
        self._fmt = fmt
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(name)
        lbl.setMinimumWidth(110)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(lo, hi)
        self.slider.setValue(value)
        self.value = QLabel()
        self.value.setMinimumWidth(56)
        self.value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.value.setObjectName("Muted")
        row.addWidget(lbl)
        row.addWidget(self.slider, 1)
        row.addWidget(self.value)
        if tip:
            self.setToolTip(tip)
        self.slider.valueChanged.connect(self._show)
        self.slider.valueChanged.connect(on_change)
        self._show(value)

    def _show(self, v):
        self.value.setText(self._fmt(v))


class MainWindow(QMainWindow):
    def __init__(self, controller: Controller):
        super().__init__()
        self.c = controller
        self._tray = None
        self._quitting = False
        self._latest_frame = None
        self._bridge = _Bridge()
        self._bridge.status.connect(self._on_status)
        controller.strip.on_status = lambda ok, port: self._bridge.status.emit(ok, port)
        controller.ambilight.on_frame = self._on_frame

        self.setWindowTitle("BuzzLight")
        self.setWindowIcon(theme.app_icon())
        self.resize(980, 680)
        self.setMinimumSize(820, 560)

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(20, 16, 20, 18)
        outer.setSpacing(14)
        outer.addLayout(self._build_header())

        body = QHBoxLayout()
        body.setSpacing(18)
        outer.addLayout(body, 1)
        self.pages = QStackedWidget()
        body.addLayout(self._build_nav(), 0)
        body.addWidget(self.pages, 1)
        self.pages.addWidget(self._build_color_page())
        self.pages.addWidget(self._build_ambilight_page())
        self.pages.addWidget(self._build_layout_page())
        self.pages.addWidget(self._build_settings_page())

        self._ui_timer = QTimer(self)
        self._ui_timer.timeout.connect(self._tick)
        self._ui_timer.start(33)

        self._on_status(controller.strip.connected, controller.strip.port)
        self._sync_from_settings()
        self._nav_buttons[1 if self.c.settings.mode == "ambilight" else 0].click()

    # --- header / nav ----------------------------------------------------------

    def _build_header(self):
        row = QHBoxLayout()
        title = QLabel("BuzzLight")
        title.setObjectName("Title")
        self.status = QLabel()
        row.addWidget(title)
        row.addSpacing(12)
        row.addWidget(self.status)
        row.addStretch(1)

        sun = QLabel("☀")
        sun.setObjectName("Muted")
        self.brightness = QSlider(Qt.Orientation.Horizontal)
        self.brightness.setRange(5, 255)
        self.brightness.setFixedWidth(200)
        self.brightness.setToolTip("Brightness")
        self.brightness.valueChanged.connect(self.c.set_brightness)
        self.power = QPushButton("⏻")
        self.power.setObjectName("Power")
        self.power.setToolTip("Turn the lights on or off")
        self.power.clicked.connect(self._toggle_power)
        row.addWidget(sun)
        row.addWidget(self.brightness)
        row.addSpacing(10)
        row.addWidget(self.power)
        return row

    def _build_nav(self):
        col = QVBoxLayout()
        col.setSpacing(4)
        self._nav_group = QButtonGroup(self)
        self._nav_buttons = []
        for i, name in enumerate(("Color", "Ambilight", "LED Setup", "Settings")):
            b = QPushButton(name)
            b.setObjectName("Nav")
            b.setCheckable(True)
            b.setMinimumWidth(150)
            b.clicked.connect(lambda _=False, i=i: self.pages.setCurrentIndex(i))
            self._nav_group.addButton(b)
            self._nav_buttons.append(b)
            col.addWidget(b)
        col.addStretch(1)
        self.mode_label = muted("")
        col.addWidget(self.mode_label)
        return col

    # --- pages -----------------------------------------------------------------

    def _build_color_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        self.picker = QColorDialog()
        self.picker.setWindowFlags(Qt.WindowType.Widget)
        self.picker.setOptions(QColorDialog.ColorDialogOption.NoButtons
                               | QColorDialog.ColorDialogOption.DontUseNativeDialog)
        self.picker.currentColorChanged.connect(self._on_pick)

        swatches = QGridLayout()
        swatches.setSpacing(8)
        for i, (name, rgb) in enumerate(PRESETS):
            b = QPushButton()
            b.setToolTip(name)
            b.setFixedHeight(30)
            b.setStyleSheet(f"background: rgb{rgb}; border: 1px solid {theme.BORDER};"
                            "border-radius: 8px;")
            b.clicked.connect(lambda _=False, rgb=rgb: self.picker.setCurrentColor(QColor(*rgb)))
            swatches.addWidget(b, 0, i)

        lay.addWidget(card(section("Presets"), swatches))
        lay.addWidget(card(section("Pick a color"), self.picker), 1)
        return page

    def _build_ambilight_page(self):
        cfg = self.c.settings.ambilight
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        self.amb_toggle = QPushButton("Start Ambilight")
        self.amb_toggle.setObjectName("Primary")
        self.amb_toggle.clicked.connect(self._toggle_ambilight)
        self.amb_stats = muted("")
        top = QHBoxLayout()
        top.addWidget(self.amb_toggle)
        top.addSpacing(12)
        top.addWidget(self.amb_stats, 1)

        self.amb_preview = StripPreview()
        lay.addWidget(card(top, self.amb_preview), 1)

        self.display = QComboBox()
        self._monitors = []
        try:
            self._monitors = list_monitors()
        except Exception as e:
            print(f"[ui] could not list displays: {e}")
        for m in self._monitors:
            self.display.addItem(m.label, m.index)
        idx = self.display.findData(cfg.monitor)
        self.display.setCurrentIndex(max(0, idx))
        self.display.currentIndexChanged.connect(self._on_display)

        self.fps = QComboBox()
        for v in (30, 60):
            self.fps.addItem(f"{v} FPS", v)
        self.fps.setCurrentIndex(1 if cfg.fps >= 60 else 0)
        self.fps.currentIndexChanged.connect(
            lambda: self.c.configure_ambilight(fps=self.fps.currentData()))

        row = QHBoxLayout()
        row.addWidget(QLabel("Display"))
        row.addWidget(self.display, 1)
        row.addSpacing(16)
        row.addWidget(QLabel("Speed"))
        row.addWidget(self.fps)

        self.smooth = LabeledSlider(
            "Smoothing", 0, 300, int(cfg.smoothing * 1000),
            lambda v: "off" if v == 0 else f"{v} ms",
            lambda v: self.c.configure_ambilight(smoothing=v / 1000),
            "How gently the lights follow the screen. Scene cuts are always fast.")
        self.sat = LabeledSlider(
            "Saturation", 50, 200, int(cfg.saturation * 100),
            lambda v: f"{v / 100:.2f}×",
            lambda v: self.c.configure_ambilight(saturation=v / 100),
            "Make colors more vivid (above 1×) or softer.")
        self.depth = LabeledSlider(
            "Edge depth", 3, 25, int(round(cfg.depth * 100)),
            lambda v: f"{v}%",
            lambda v: self.c.configure_ambilight(depth=v / 100),
            "How far into the picture each LED looks.")
        self.bars = QCheckBox("Ignore black bars (letterbox / pillarbox)")
        self.bars.setChecked(cfg.black_bars)
        self.bars.setToolTip("Follow the picture's edges when a video or game doesn't "
                             "fill the screen, e.g. 16:9 video on an ultrawide.")
        self.bars.toggled.connect(lambda v: self.c.configure_ambilight(black_bars=v))
        self.dxgi = QCheckBox("Fast capture (DirectX)")
        self.dxgi.setChecked(cfg.prefer_dxgi)
        self.dxgi.setToolTip("Uses Desktop Duplication. Turn off if the lights stay dark "
                             "or a game shows a black screen to capture tools.")
        self.dxgi.toggled.connect(lambda v: self.c.configure_ambilight(prefer_dxgi=v))

        lay.addWidget(card(section("Picture"), row, self.smooth, self.sat, self.depth,
                           self.bars, self.dxgi))
        return page

    def _build_layout_page(self):
        lay_cfg = self.c.settings.ambilight.layout
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        self.layout_preview = StripPreview(show_order=True)
        self.layout_preview.set_layout(lay_cfg)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        self.side_spins = {}
        for i, side in enumerate(("top", "right", "bottom", "left")):
            sp = QSpinBox()
            sp.setRange(0, LED_COUNT)
            sp.setValue(lay_cfg.count(side))
            sp.valueChanged.connect(self._on_layout_edit)
            self.side_spins[side] = sp
            grid.addWidget(QLabel(f"{side.capitalize()} LEDs"), i // 2, (i % 2) * 2)
            grid.addWidget(sp, i // 2, (i % 2) * 2 + 1)

        self.start_corner = QComboBox()
        for corner in CORNERS:
            self.start_corner.addItem(corner.replace("-", " ").capitalize(), corner)
        self.start_corner.setCurrentIndex(CORNERS.index(lay_cfg.start))
        self.start_corner.currentIndexChanged.connect(self._on_layout_edit)
        self.direction = QComboBox()
        self.direction.addItem("Clockwise", True)
        self.direction.addItem("Counter-clockwise", False)
        self.direction.setCurrentIndex(0 if lay_cfg.clockwise else 1)
        self.direction.currentIndexChanged.connect(self._on_layout_edit)
        self.offset = QSpinBox()
        self.offset.setRange(0, LED_COUNT)
        self.offset.setValue(lay_cfg.offset)
        self.offset.setToolTip("LEDs at the start of the strip that aren't on the screen edge.")
        self.offset.valueChanged.connect(self._on_layout_edit)
        grid.addWidget(QLabel("Strip starts at"), 2, 0)
        grid.addWidget(self.start_corner, 2, 1)
        grid.addWidget(QLabel("Runs"), 2, 2)
        grid.addWidget(self.direction, 2, 3)
        grid.addWidget(QLabel("Skip first"), 3, 0)
        grid.addWidget(self.offset, 3, 1)
        self.total = muted("")
        grid.addWidget(self.total, 3, 2, 1, 2)

        self.identify_btn = QPushButton("Identify on strip")
        self.identify_btn.setObjectName("Primary")
        self.identify_btn.clicked.connect(lambda: self.c.identify())
        help_ = muted("Identify lights each side in its own color for a few seconds: "
                      "top blue, right yellow, bottom red, left green, and the first LED "
                      "white. Adjust until the strip matches the picture above.")
        actions = QHBoxLayout()
        actions.addWidget(self.identify_btn)
        actions.addStretch(1)

        lay.addWidget(card(section("Strip layout (front view)"), self.layout_preview), 1)
        lay.addWidget(card(grid, help_, actions))
        self._update_total()
        return page

    def _build_settings_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        self.autostart_cb = QCheckBox("Start with Windows (minimized to the tray)")
        self.autostart_cb.setEnabled(autostart.supported())
        self.autostart_cb.setChecked(autostart.enabled())
        self.autostart_cb.toggled.connect(self._on_autostart)
        startup = card(section("Startup"), self.autostart_cb,
                       muted("Closing the window keeps BuzzLight running in the tray. "
                             "Right-click the tray icon to quit."))

        open_folder = QPushButton("Open settings folder")
        open_folder.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(config_dir())))
        row = QHBoxLayout()
        row.addWidget(open_folder)
        row.addStretch(1)
        about = card(section("About"),
                     QLabel(f"BuzzLight {__version__}"),
                     muted("Ambient lighting for USB LED strip kits (Lytmi / Beelight "
                           "controllers, USB 2E3C:5740)."), row)
        lay.addWidget(startup)
        lay.addWidget(about)
        lay.addStretch(1)
        return page

    # --- state → UI --------------------------------------------------------------

    def _sync_from_settings(self):
        s = self.c.settings
        self.brightness.blockSignals(True)
        self.brightness.setValue(max(5, s.brightness))
        self.brightness.blockSignals(False)
        self.power.setProperty("on", s.power)
        self.power.style().unpolish(self.power)
        self.power.style().polish(self.power)
        self.picker.blockSignals(True)
        self.picker.setCurrentColor(QColor(*s.color))
        self.picker.blockSignals(False)
        amb = s.power and s.mode == "ambilight"
        self.amb_toggle.setText("Stop Ambilight" if amb else "Start Ambilight")
        if not s.power:
            self.mode_label.setText("Lights off")
        else:
            self.mode_label.setText("Mode: Ambilight" if s.mode == "ambilight" else "Mode: Color")

    def _on_status(self, connected: bool, port):
        if connected:
            self.status.setText(f"<span style='color:{theme.GOOD}'>●</span> Connected · {port}")
        else:
            self.status.setText(f"<span style='color:{theme.BAD}'>●</span> "
                                "Looking for the LED strip…")
        if self._tray:
            self._tray.set_connected(connected, port)

    def _on_frame(self, frame):
        self._latest_frame = frame          # engine thread; painted by _tick

    def _tick(self):
        s = self.c.settings
        st = self.c.ambilight.stats
        if s.power and s.mode == "ambilight" and self.c.ambilight.running:
            frame = self._latest_frame
            bars = st.bars
            bar_txt = ""
            if bars.left:
                bar_txt = f" · side bars {bars.left}px"
            elif bars.top:
                bar_txt = f" · top/bottom bars {bars.top}px"
            text = f"{st.backend} · {st.fps:.0f} FPS{bar_txt}"
            if st.error:
                text = f"<span style='color:{theme.BAD}'>{st.error}</span>"
            self.amb_stats.setText(text)
        else:
            frame = [s.color if s.power else (0, 0, 0)] * LED_COUNT
            self.amb_stats.setText("Ambilight is off" if s.power else "Lights are off")
        if self.isVisible():
            lay = s.ambilight.layout
            self.amb_preview.set_layout(lay)
            self.amb_preview.set_frame(frame)
            mon = next((m for m in self._monitors if m.index == s.ambilight.monitor), None)
            if mon:
                self.amb_preview.set_aspect(mon.width, mon.height)
                self.layout_preview.set_aspect(mon.width, mon.height)

    # --- UI → controller -----------------------------------------------------------

    def _toggle_power(self):
        self.c.toggle_power()
        self._sync_from_settings()

    def _on_pick(self, color: QColor):
        if color.isValid():
            self.c.set_color((color.red(), color.green(), color.blue()))
            self._sync_from_settings()

    def _toggle_ambilight(self):
        s = self.c.settings
        if s.power and s.mode == "ambilight":
            self.c.set_mode("color")
        else:
            self.c.set_mode("ambilight")
        self._sync_from_settings()

    def _on_display(self):
        idx = self.display.currentData()
        if idx is not None:
            self.c.configure_ambilight(monitor=int(idx))

    def _layout_from_ui(self) -> Layout:
        return Layout(top=self.side_spins["top"].value(),
                      right=self.side_spins["right"].value(),
                      bottom=self.side_spins["bottom"].value(),
                      left=self.side_spins["left"].value(),
                      start=self.start_corner.currentData(),
                      clockwise=self.direction.currentData(),
                      offset=self.offset.value())

    def _on_layout_edit(self):
        lay = self._layout_from_ui()
        self.c.set_layout(lay)
        self.layout_preview.set_layout(self.c.settings.ambilight.layout)
        self._update_total()
        if self.c.identifying:
            self.c.identify()               # refresh the test pattern live

    def _update_total(self):
        raw = (sum(sp.value() for sp in self.side_spins.values()) + self.offset.value())
        if raw > LED_COUNT:
            self.total.setText(f"<span style='color:{theme.BAD}'>{raw} LEDs — the "
                               f"controller drives {LED_COUNT}; extra LEDs are ignored</span>")
        else:
            self.total.setText(f"{raw} of {LED_COUNT} LEDs used")

    def _on_autostart(self, on: bool):
        try:
            autostart.set_enabled(on)
        except OSError as e:
            QMessageBox.warning(self, "Start with Windows", f"Couldn't change it:\n{e}")
            self.autostart_cb.blockSignals(True)
            self.autostart_cb.setChecked(autostart.enabled())
            self.autostart_cb.blockSignals(False)
        if self._tray:
            self._tray.sync()

    # --- tray integration --------------------------------------------------------

    def attach_tray(self, tray) -> None:
        self._tray = tray
        tray.set_connected(self.c.strip.connected, self.c.strip.port)

    def refresh(self) -> None:
        """Re-read state changed elsewhere (e.g. from the tray menu)."""
        self._sync_from_settings()
        self.autostart_cb.blockSignals(True)
        self.autostart_cb.setChecked(autostart.enabled())
        self.autostart_cb.blockSignals(False)

    def request_quit(self) -> None:
        self._quitting = True
        self.close()

    def closeEvent(self, event):
        if self._tray is not None and not self._quitting:
            event.ignore()
            self.hide()
            self._tray.hint_once()
            return
        self._ui_timer.stop()
        event.accept()

