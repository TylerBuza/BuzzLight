"""Ambilight: capture → black bars → sample → smooth → strip, on a thread."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field, replace
from typing import Callable, Optional

import numpy as np

from buzzlight.ambilight import letterbox
from buzzlight.ambilight.capture import list_monitors, open_capture
from buzzlight.ambilight.sampler import Smoother, sample, saturate
from buzzlight.device.protocol import LED_COUNT
from buzzlight.layout import Layout

RGB = tuple[int, int, int]


@dataclass(frozen=True)
class AmbilightConfig:
    monitor: int = 1                 # 1-based display index
    fps: int = 60
    depth: float = 0.08              # sampled band, fraction of short side
    smoothing: float = 0.08          # seconds (time constant), 0 = off
    saturation: float = 1.2
    spread: float = 1.0
    black_bars: bool = True
    prefer_dxgi: bool = True
    layout: Layout = field(default_factory=Layout)

    @classmethod
    def from_dict(cls, d: dict | None) -> "AmbilightConfig":
        d = dict(d or {})
        layout = Layout.from_dict(d.pop("layout", None))
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(layout=layout, **known)

    def to_dict(self) -> dict:
        d = {k: getattr(self, k) for k in self.__dataclass_fields__}
        d["layout"] = self.layout.to_dict()
        return d


@dataclass
class Stats:
    fps: float = 0.0
    backend: str = ""
    bars: letterbox.Bars = letterbox.NONE
    error: str = ""


class Ambilight:
    PROBE_EVERY = 0.5

    def __init__(self, strip, config: AmbilightConfig | None = None):
        self._strip = strip
        self._config = config or AmbilightConfig()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.stats = Stats()
        self.on_frame: Optional[Callable[[list[RGB]], None]] = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def config(self) -> AmbilightConfig:
        with self._lock:
            return self._config

    def configure(self, **changes) -> None:
        with self._lock:
            self._config = replace(self._config, **changes)

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="ambilight", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None

    # --- worker --------------------------------------------------------------

    def _open(self, cfg: AmbilightConfig):
        monitors = list_monitors()
        mon = next((m for m in monitors if m.index == cfg.monitor), monitors[0])
        cap = open_capture(mon, cfg.prefer_dxgi)
        self.stats.backend = cap.name
        return cap

    def _run(self) -> None:
        cap = None
        opened_for = None
        smoother = Smoother()
        tracker = letterbox.Tracker()
        next_probe = 0.0
        last = time.monotonic()
        frames, fps_t0 = 0, last

        while not self._stop.is_set():
            cfg = self.config
            t0 = time.monotonic()
            try:
                key = (cfg.monitor, cfg.prefer_dxgi)
                if cap is None or opened_for != key:
                    if cap is not None:
                        cap.close()
                    cap = self._open(cfg)
                    opened_for = key
                    tracker.reset()
                    smoother.reset()
                    next_probe = 0.0
                w, h = cap.size

                if not cfg.black_bars:
                    tracker.reset()
                elif t0 >= next_probe:
                    probe = cap.grab(letterbox.probe_depth(w, h))
                    tracker.update(*letterbox.measure(probe), w, h)
                    cost = time.monotonic() - t0
                    # Slow backends probe less often (≤ ~5% of the time),
                    # but confirm a new measurement quickly.
                    gap = min(2.0, max(self.PROBE_EVERY, cost * 20))
                    if tracker.pending:
                        gap = 0.25
                    next_probe = time.monotonic() + gap
                bars = tracker.bars

                cw = w - bars.left - bars.right
                ch = h - bars.top - bars.bottom
                depth = max(4, int(cfg.depth * min(cw, ch)))
                if bars.any:
                    edges = letterbox.crop(
                        cap.grab(letterbox.capture_depths(bars, depth)), bars, depth)
                else:
                    edges = cap.grab(depth)

                leds = cfg.layout.leds()
                colors = sample(edges, leds, cfg.spread)
                colors = saturate(colors, cfg.saturation)
                colors[colors.max(axis=1) < 4] = 0          # true black
                smoother.tau = cfg.smoothing
                now = time.monotonic()
                colors = smoother(colors, now - last)
                last = now

                frame = [(0, 0, 0)] * LED_COUNT
                for led, c in zip(leds, np.rint(colors).astype(int).tolist()):
                    frame[led.index] = tuple(c)
                self._strip.set_frame(frame)
                if self.on_frame:
                    self.on_frame(frame)

                frames += 1
                if now - fps_t0 >= 1.0:
                    self.stats.fps = frames / (now - fps_t0)
                    frames, fps_t0 = 0, now
                self.stats.bars = bars
                self.stats.error = ""
            except Exception as e:
                # Display mode changes, UAC prompts and sleep make capture
                # fail temporarily: report, rebuild the capture, retry.
                self.stats.error = f"{type(e).__name__}: {e}"
                print(f"[ambilight] {self.stats.error}")
                if cap is not None:
                    try:
                        cap.close()
                    except Exception:
                        pass
                cap = None
                self._stop.wait(1.0)
                continue

            spent = time.monotonic() - t0
            self._stop.wait(max(0.0, 1.0 / max(1, cfg.fps) - spent))

        if cap is not None:
            cap.close()
