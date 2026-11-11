"""Black-bar (letterbox / pillarbox) detection.

16:9 video on a 21:9 ultrawide leaves wide black bars at the sides; movies
on 16:9 screens leave bars top and bottom. Edge sampling would read those
bars as black, so we measure them and sample at the picture's edges.

Pure numpy over `Edges` strips, so it works with every capture backend.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from buzzlight.ambilight.capture import Edges

LIT = 28                # brightest channel above this = a lit pixel
BLACK_FRACTION = 0.004  # a line is black if fewer pixels than this are lit
MIN_BAR = 0.015         # ignore bars thinner than this fraction
TOLERANCE = 0.015       # left/right must match within this fraction
PROBE = 0.3             # how deep to look, fraction of the larger dimension
MAX_BAR = 0.4           # never crop more than this per side
_ALONG, _ACROSS = 2, 8  # subsampling (accuracy ±2 px, keeps a probe ~ms)


@dataclass(frozen=True)
class Bars:
    left: int = 0
    top: int = 0
    right: int = 0
    bottom: int = 0

    @property
    def any(self) -> bool:
        return bool(self.left or self.top or self.right or self.bottom)


NONE = Bars()


def probe_depth(w: int, h: int) -> int:
    return max(1, int(PROBE * max(w, h)))


def _black_run(strip: np.ndarray, across_rows: bool, reverse: bool) -> tuple[int, bool]:
    """Length of the black run from one end of a strip, and whether the
    whole visible strip was black."""
    sub = strip[::_ACROSS, ::_ALONG] if across_rows else strip[::_ALONG, ::_ACROSS]
    lit = (sub.max(axis=2) > LIT).mean(axis=0 if across_rows else 1)
    if reverse:
        lit = lit[::-1]
    black = lit < BLACK_FRACTION
    if black.all():
        return len(black) * _ALONG, True
    return int(np.argmin(black)) * _ALONG, False


def measure(e: Edges) -> tuple[Optional[int], Optional[int]]:
    """(side bar width, top bar height) from a probe; None = can't tell
    (dark scene, or the bar is deeper than the probe)."""
    w, h = e.width, e.height
    left, l_all = _black_run(e.left, True, False)
    right, r_all = _black_run(e.right, True, True)
    if l_all or r_all:
        horiz = None
    elif abs(left - right) <= TOLERANCE * w:
        horiz = min(left, right)
        horiz = horiz if horiz >= MIN_BAR * w else 0
    else:
        horiz = 0                       # one-sided: a dark window, not bars

    # Subtitles often sit inside the bottom bar: size bars from the top, and
    # only require the bottom bar to start out black.
    top, t_all = _black_run(e.top, False, False)
    bottom, b_all = _black_run(e.bottom, False, True)
    if t_all or b_all:
        vert = None
    elif top < MIN_BAR * h:
        vert = 0
    elif max(2, 0.25 * top) <= bottom <= top + TOLERANCE * h:
        vert = top
    else:
        vert = 0
    return horiz, vert


class Tracker:
    """Applies a measurement only after `confirm` matching probes in a row,
    so dark scenes and fades don't make the crop jump around."""

    def __init__(self, confirm: int = 2):
        self.confirm = confirm
        self.bars = NONE
        self._pending: dict[str, tuple[int, int]] = {}

    def reset(self) -> None:
        self.bars = NONE
        self._pending.clear()

    @property
    def pending(self) -> bool:
        """A new measurement is waiting for confirmation."""
        return bool(self._pending)

    def _axis(self, key: str, current: int, measured: Optional[int], tol: int) -> int:
        if measured is None or abs(measured - current) <= tol:
            self._pending.pop(key, None)
            return current
        value, n = self._pending.get(key, (measured, 0))
        n = n + 1 if abs(value - measured) <= tol else 1
        if n >= self.confirm:
            self._pending.pop(key, None)
            return measured
        self._pending[key] = (measured, n)
        return current

    def update(self, horiz: Optional[int], vert: Optional[int], w: int, h: int) -> Bars:
        hb = self._axis("h", self.bars.left, horiz, max(2, int(TOLERANCE * w)))
        vb = self._axis("v", self.bars.top, vert, max(2, int(TOLERANCE * h)))
        hb, vb = min(hb, int(MAX_BAR * w)), min(vb, int(MAX_BAR * h))
        self.bars = Bars(hb, vb, hb, vb)
        return self.bars


def capture_depths(bars: Bars, depth: int) -> dict[str, int]:
    """Per-side strip depth needed to reach `depth` px past each bar."""
    return {"top": depth + bars.top, "bottom": depth + bars.bottom,
            "left": depth + bars.left, "right": depth + bars.right}


def crop(e: Edges, bars: Bars, depth: int) -> Edges:
    """Re-anchor full-screen strips (captured with capture_depths) to the
    picture's edges. The result describes the picture as if it were the
    whole screen."""
    w, h = e.width, e.height
    x0, x1 = bars.left, max(bars.left + 1, w - bars.right)
    y0, y1 = bars.top, max(bars.top + 1, h - bars.bottom)

    def rows(a, start, stop):
        start = max(0, min(a.shape[0] - 1, start))
        return a[start:max(start + 1, min(a.shape[0], stop))]

    def cols(a, start, stop):
        start = max(0, min(a.shape[1] - 1, start))
        return a[:, start:max(start + 1, min(a.shape[1], stop))]

    nb, nr = e.bottom.shape[0], e.right.shape[1]
    return Edges(
        x1 - x0, y1 - y0,
        top=cols(rows(e.top, bars.top, bars.top + depth), x0, x1),
        bottom=cols(rows(e.bottom, nb - bars.bottom - depth, nb - bars.bottom), x0, x1),
        left=rows(cols(e.left, bars.left, bars.left + depth), y0, y1),
        right=rows(cols(e.right, nr - bars.right - depth, nr - bars.right), y0, y1),
    )
