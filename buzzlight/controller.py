"""Controller: the app's state machine, independent of any UI.

Owns the Strip and the Ambilight engine, applies settings to them, and
persists every change (debounced).
"""

from __future__ import annotations

import threading
from dataclasses import replace
from typing import Callable, Optional

from buzzlight import settings as settings_mod
from buzzlight.ambilight.engine import Ambilight
from buzzlight.device.strip import Strip
from buzzlight.layout import Layout, identify_frame

RGB = tuple[int, int, int]


class Controller:
    SAVE_DELAY = 0.8

    def __init__(self, strip: Strip | None = None, settings=None,
                 save: Callable | None = None):
        self.settings = settings or settings_mod.load()
        self._save = save or settings_mod.save
        self.strip = strip or Strip()
        self.ambilight = Ambilight(self.strip, self.settings.ambilight)
        self._save_timer: threading.Timer | None = None
        self._identify_timer: threading.Timer | None = None
        self.on_change: Optional[Callable[[], None]] = None

    # --- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        s = self.settings
        self.strip.set_brightness(s.brightness)
        self.strip.set_power(s.power)
        self.strip.start()
        self._apply_mode()

    def shutdown(self) -> None:
        self.ambilight.stop()
        self.flush()
        self.strip.stop(turn_off=True)

    def flush(self) -> None:
        if self._save_timer:
            self._save_timer.cancel()
            self._save_timer = None
        self._save(self.settings)

    def _changed(self) -> None:
        if self._save_timer:
            self._save_timer.cancel()
        self._save_timer = threading.Timer(self.SAVE_DELAY, self._save, (self.settings,))
        self._save_timer.daemon = True
        self._save_timer.start()
        if self.on_change:
            self.on_change()

    # --- actions -------------------------------------------------------------

    def set_power(self, on: bool) -> None:
        self.settings.power = bool(on)
        self.strip.set_power(on)
        self._apply_mode()
        self._changed()

    def toggle_power(self) -> None:
        self.set_power(not self.settings.power)

    def set_brightness(self, value: int) -> None:
        self.settings.brightness = max(0, min(255, int(value)))
        self.strip.set_brightness(self.settings.brightness)
        self._changed()

    def set_mode(self, mode: str) -> None:
        if mode not in settings_mod.MODES:
            raise ValueError(mode)
        self.settings.mode = mode
        if not self.settings.power:
            self.settings.power = True
            self.strip.set_power(True)
        self._apply_mode()
        self._changed()

    def set_color(self, color: RGB) -> None:
        self.settings.color = tuple(max(0, min(255, int(c))) for c in color)
        self.settings.mode = "color"
        self._apply_mode()
        self._changed()

    def configure_ambilight(self, **changes) -> None:
        cfg = replace(self.settings.ambilight, **changes)
        self.settings.ambilight = cfg
        self.ambilight.configure(**changes)
        self._changed()

    def set_layout(self, layout: Layout) -> None:
        self.configure_ambilight(layout=Layout.from_dict(layout.to_dict()))

    def identify(self, seconds: float = 6.0) -> None:
        """Show the layout test pattern, then go back to the current mode."""
        self.ambilight.stop()
        self.strip.set_power(True)
        self.strip.set_frame(identify_frame(self.settings.ambilight.layout))
        if self._identify_timer:
            self._identify_timer.cancel()
        self._identify_timer = threading.Timer(seconds, self._end_identify)
        self._identify_timer.daemon = True
        self._identify_timer.start()

    def _end_identify(self) -> None:
        self._identify_timer = None
        self.strip.set_power(self.settings.power)
        self._apply_mode()

    @property
    def identifying(self) -> bool:
        return self._identify_timer is not None

    def _apply_mode(self) -> None:
        if self._identify_timer is not None:
            return
        s = self.settings
        if s.power and s.mode == "ambilight":
            self.ambilight.configure(**{k: getattr(s.ambilight, k)
                                        for k in s.ambilight.__dataclass_fields__})
            self.ambilight.start()
        else:
            self.ambilight.stop()
            if s.power:
                self.strip.set_color(s.color)
