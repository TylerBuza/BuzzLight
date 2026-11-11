"""Strip: owns the serial link to one LED controller.

All I/O happens on a single background thread. Callers just describe what
the strip should show (power, brightness, a solid color or a per-LED frame)
and the thread keeps the hardware in that state: it handles the wake-up
handshake, heartbeats, periodic refreshes, smooth color fades, and
reconnecting after the cable is unplugged.
"""

from __future__ import annotations

import math
import threading
import time
from typing import Callable, Optional, Sequence

import serial

from buzzlight.device import protocol as p
from buzzlight.device.ports import find_controller

RGB = tuple[int, int, int]

BAUD = 500_000
TICK = 0.015            # ~66 packets/s ceiling
HEARTBEAT_EVERY = 0.15
REFRESH_EVERY = 0.5     # re-assert state even when unchanged
RECONNECT_EVERY = 2.0
FADE_TIME = 0.08        # time constant of solid-color fades (s)
MAX_WRITE_ERRORS = 3

StatusCallback = Callable[[bool, Optional[str]], None]


class Strip:
    def __init__(self, port: str | None = None,
                 opener: Callable[..., object] | None = None):
        self._fixed_port = port
        self._open = opener or serial.Serial
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        # desired state (guarded by _lock)
        self._power = True
        self._brightness = 255
        self._color: tuple[float, float, float] | None = None  # target
        self._frame: list[RGB] | None = None
        self._frame_seq = 0

        # link state (thread only)
        self._ser = None
        self._errors = 0
        self.port: str | None = None
        self.connected = False
        self.on_status: StatusCallback | None = None

    # --- public API (any thread) ---------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="strip",
                                        daemon=True)
        self._thread.start()

    def stop(self, turn_off: bool = False) -> None:
        if turn_off:
            self.set_power(False)
            time.sleep(0.1)
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None

    def set_power(self, on: bool) -> None:
        with self._lock:
            self._power = bool(on)
        self._wake.set()

    def set_brightness(self, value: int) -> None:
        with self._lock:
            self._brightness = max(0, min(255, int(value)))
        self._wake.set()

    def set_color(self, color: RGB) -> None:
        """Show one color on every LED (fades from the current color)."""
        with self._lock:
            self._color = tuple(float(c) for c in color)
            self._frame = None
        self._wake.set()

    def set_frame(self, colors: Sequence[RGB]) -> None:
        """Show per-LED colors; colors[0] is the LED nearest the input."""
        with self._lock:
            self._frame = list(colors)
            self._frame_seq += 1
            self._color = None
        self._wake.set()

    @property
    def power(self) -> bool:
        return self._power

    @property
    def brightness(self) -> int:
        return self._brightness

    # --- link ----------------------------------------------------------------

    def _notify(self) -> None:
        cb = self.on_status
        if cb:
            try:
                cb(self.connected, self.port)
            except Exception as e:
                print(f"[strip] status callback failed: {e}")

    def _connect(self) -> bool:
        port = self._fixed_port or find_controller()
        if not port:
            return False
        try:
            ser = self._open(port=port, baudrate=BAUD, timeout=0,
                             write_timeout=0.5)
        except (serial.SerialException, OSError) as e:
            print(f"[strip] cannot open {port}: {e}")
            return False
        try:
            ser.dtr = True
            ser.rts = True
        except (serial.SerialException, OSError, AttributeError):
            pass
        self._ser = ser
        self.port = port
        self._errors = 0
        if not self._stop.wait(0.3):
            self._drain()
        for pkt in p.wake_sequence():
            self._write(pkt)
            if self._stop.wait(0.05):
                break
        # dim to zero before power-on so the old state doesn't flash
        for pkt in (p.dimmer(0), p.power(True), p.dimmer(0), p.work_mode()):
            self._write(pkt)
            self._stop.wait(0.02)
        self._drain()
        if self._ser is None:      # handshake writes failed
            return False
        self.connected = True
        print(f"[strip] connected on {port}")
        self._notify()
        return True

    def _disconnect(self, reason: str) -> None:
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
        self._ser = None
        was = self.connected
        self.connected = False
        if was:
            print(f"[strip] disconnected from {self.port}: {reason}")
            self._notify()
        self.port = None

    def _write(self, pkt: bytes) -> None:
        if self._ser is None:
            return
        try:
            self._ser.write(pkt)
            self._errors = 0
        except (serial.SerialException, OSError) as e:
            self._errors += 1
            if self._errors >= MAX_WRITE_ERRORS:
                self._disconnect(f"write failed: {e}")

    def _drain(self) -> None:
        try:
            if self._ser is not None and self._ser.in_waiting:
                self._ser.read(self._ser.in_waiting)
        except (serial.SerialException, OSError):
            pass

    # --- main loop -----------------------------------------------------------

    def _run(self) -> None:
        next_connect = 0.0
        while not self._stop.is_set():
            if self._ser is None:
                now = time.monotonic()
                if now >= next_connect:
                    next_connect = now + RECONNECT_EVERY
                    if self._connect():
                        self._session()
                        continue
                self._stop.wait(max(0.05, next_connect - time.monotonic()))
                continue
        self._disconnect("stopped")

    def _session(self) -> None:
        """Keep the connected strip in the desired state until the link
        drops or stop() is called."""
        shown: tuple[float, float, float] | None = None  # faded solid color
        sent_power = sent_bright = None
        sent_frame_seq = -1
        sent_solid: RGB | None = None
        last_hb = last_refresh = last_drain = 0.0
        last_tick = time.monotonic()

        while self._ser is not None and not self._stop.is_set():
            now = time.monotonic()
            dt = now - last_tick
            last_tick = now
            refresh = now - last_refresh >= REFRESH_EVERY
            if refresh:
                last_refresh = now

            with self._lock:
                power, bright = self._power, self._brightness
                target, frame, seq = self._color, self._frame, self._frame_seq

            if power != sent_power or refresh:
                if power != sent_power:
                    sent_solid, sent_frame_seq = None, -1  # re-show content
                self._write(p.power(power))
                sent_power = power
            if bright != sent_bright or refresh:
                self._write(p.brightness(bright))
                sent_bright = bright

            if power and frame is not None:
                shown = None
                sent_solid = None
                if seq != sent_frame_seq or refresh:
                    self._write(p.frame(frame))
                    sent_frame_seq = seq
            elif power and target is not None:
                sent_frame_seq = -1
                if shown is None:
                    shown = target
                else:
                    k = 1.0 - math.exp(-dt / FADE_TIME)
                    shown = tuple(s + (t - s) * k for s, t in zip(shown, target))
                    if all(abs(s - t) < 0.5 for s, t in zip(shown, target)):
                        shown = target
                rgb = tuple(int(round(c)) for c in shown)
                if rgb != sent_solid or refresh:
                    self._write(p.solid(rgb))
                    sent_solid = rgb

            if now - last_hb >= HEARTBEAT_EVERY:
                self._write(p.heartbeat())
                last_hb = now
            if now - last_drain >= 1.0:
                self._drain()
                last_drain = now

            fading = shown is not None and target is not None and shown != target
            # Sleep one tick; while idle, sleep until something changes or
            # the next heartbeat is due.
            wait = TICK if fading else max(
                TICK, min(HEARTBEAT_EVERY - (time.monotonic() - last_hb),
                          REFRESH_EVERY - (time.monotonic() - last_refresh)))
            self._wake.wait(wait)
            self._wake.clear()
            if not fading:
                # don't exceed the packet-rate ceiling when updates stream in
                spent = time.monotonic() - now
                if spent < TICK:
                    self._stop.wait(TICK - spent)
