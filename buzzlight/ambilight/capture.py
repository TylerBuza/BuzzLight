"""Screen capture of the four screen-edge strips.

Two backends:
  * DXGI (bettercam, Desktop Duplication): one GPU grab of the whole
    screen per frame; edge strips are free numpy views. Fast.
  * GDI (mss): grabs only the four strips. Works everywhere; slower.

`Edges` holds RGB uint8 arrays:
  top    (depth_top, W, 3)      bottom (depth_bottom, W, 3)
  left   (H, depth_left, 3)     right  (H, depth_right, 3)
"""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass

import numpy as np

SIDES = ("top", "right", "bottom", "left")


def make_dpi_aware() -> None:
    """Without this, Windows display scaling (e.g. 125%) makes capture APIs
    report a virtualised, smaller screen and grab only part of it."""
    if sys.platform != "win32":
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


make_dpi_aware()


@dataclass
class Edges:
    width: int
    height: int
    top: np.ndarray
    right: np.ndarray
    bottom: np.ndarray
    left: np.ndarray

    def side(self, name: str) -> np.ndarray:
        return getattr(self, name)


@dataclass(frozen=True)
class Monitor:
    index: int          # 1-based, matches mss.monitors[index]
    left: int
    top: int
    width: int
    height: int

    @property
    def label(self) -> str:
        return f"Display {self.index} — {self.width}×{self.height}"


def list_monitors() -> list[Monitor]:
    import mss
    with mss.mss() as sct:
        return [Monitor(i, m["left"], m["top"], m["width"], m["height"])
                for i, m in enumerate(sct.monitors) if i > 0]


def _depths(depth, w: int, h: int) -> dict[str, int]:
    if isinstance(depth, dict):
        d = {s: depth.get(s, 1) for s in SIDES}
    else:
        d = dict.fromkeys(SIDES, depth)
    return {s: max(1, min(int(v), h if s in ("top", "bottom") else w))
            for s, v in d.items()}


def _slice(rgb: np.ndarray, depth) -> Edges:
    h, w = rgb.shape[:2]
    d = _depths(depth, w, h)
    return Edges(w, h,
                 top=rgb[:d["top"]],
                 right=rgb[:, w - d["right"]:],
                 bottom=rgb[h - d["bottom"]:],
                 left=rgb[:, :d["left"]])


class GdiCapture:
    name = "GDI (mss)"

    def __init__(self, monitor: Monitor):
        self.monitor = monitor
        self._sct = None

    @property
    def size(self) -> tuple[int, int]:
        return self.monitor.width, self.monitor.height

    def grab(self, depth) -> Edges:
        import mss
        if self._sct is None:
            self._sct = mss.mss()      # mss handles are per-thread
        m = self.monitor
        w, h = m.width, m.height
        d = _depths(depth, w, h)
        boxes = {
            "top": (0, 0, w, d["top"]),
            "bottom": (0, h - d["bottom"], w, d["bottom"]),
            "left": (0, 0, d["left"], h),
            "right": (w - d["right"], 0, d["right"], h),
        }
        out = {}
        for side, (x, y, bw, bh) in boxes.items():
            shot = self._sct.grab({"left": m.left + x, "top": m.top + y,
                                   "width": bw, "height": bh})
            bgra = np.frombuffer(shot.raw, np.uint8).reshape(shot.height, shot.width, 4)
            out[side] = bgra[:, :, 2::-1]
        return Edges(w, h, **out)

    def close(self) -> None:
        if self._sct is not None:
            self._sct.close()
            self._sct = None


class DxgiCapture:
    name = "DirectX (BetterCam)"

    def __init__(self, monitor: Monitor):
        import bettercam
        _com_init()
        self.monitor = monitor
        cam = None
        # Desktop Duplication enumerates outputs per GPU; find the one whose
        # size matches the chosen monitor (index order usually matches).
        for out_idx in [monitor.index - 1] + list(range(4)):
            try:
                # BGRA: no colour conversion inside bettercam (that path
                # needs OpenCV); we reorder channels with a numpy view.
                cam = bettercam.create(device_idx=0, output_idx=out_idx,
                                       output_color="BGRA")
            except Exception:
                cam = None
            if cam is not None and (cam.width, cam.height) == (monitor.width, monitor.height):
                break
            if cam is not None:
                cam.release()
                cam = None
        if cam is None:
            raise RuntimeError("Desktop Duplication unavailable for this display")
        self._cam = cam
        self._last: np.ndarray | None = None
        self._gdi: GdiCapture | None = None

    @property
    def size(self) -> tuple[int, int]:
        return self._cam.width, self._cam.height

    def grab(self, depth) -> Edges:
        bgra = self._cam.grab()         # None when the screen hasn't changed
        if bgra is not None and (self._last is not None or bgra[::16, ::16, :3].any()):
            # keep our own copy: bettercam reuses its buffer
            self._last = np.array(bgra, copy=True)[:, :, 2::-1]
        if self._last is None:
            # Desktop Duplication returns nothing until the screen changes,
            # and its first frame is often all black. Until a real frame
            # arrives, read the screen through GDI instead.
            if self._gdi is None:
                self._gdi = GdiCapture(self.monitor)
            return self._gdi.grab(depth)
        if self._gdi is not None:
            self._gdi.close()
            self._gdi = None
        return _slice(self._last, depth)

    def close(self) -> None:
        try:
            self._cam.release()
        except Exception:
            pass
        if self._gdi is not None:
            self._gdi.close()
            self._gdi = None
        self._last = None


_com = threading.local()


def _com_init() -> None:
    if sys.platform != "win32" or getattr(_com, "done", False):
        return
    try:
        import comtypes
        comtypes.CoInitialize()
        _com.done = True
    except Exception:
        pass


def open_capture(monitor: Monitor, prefer_dxgi: bool = True):
    """Best available backend for `monitor` (DXGI if possible)."""
    if prefer_dxgi and sys.platform == "win32":
        try:
            return DxgiCapture(monitor)
        except Exception as e:
            print(f"[capture] DirectX capture unavailable ({e}); using GDI")
    return GdiCapture(monitor)
