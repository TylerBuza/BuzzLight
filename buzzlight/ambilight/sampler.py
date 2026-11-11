"""Turn screen-edge strips into one color per LED."""

from __future__ import annotations

import numpy as np

from buzzlight.ambilight.capture import Edges
from buzzlight.layout import Led

# Subsampling: pixels along the edge and into the screen. Plenty for
# averages and keeps a 3440x1440 frame well under a millisecond.
STEP_ALONG = 2
STEP_DEPTH = 4


def _profile(strip: np.ndarray, horizontal: bool) -> np.ndarray:
    """Mean linear-light color for each position along an edge strip.
    Averaging squared values (≈ gamma 2) keeps a bright object on a dark
    background from turning into murky grey."""
    if horizontal:                          # top/bottom: (depth, W, 3)
        sub = strip[::STEP_DEPTH, ::STEP_ALONG]
        axis = 0
    else:                                   # left/right: (H, depth, 3)
        sub = strip[::STEP_ALONG, ::STEP_DEPTH]
        axis = 1
    lin = sub.astype(np.float32)
    lin *= lin
    return lin.mean(axis=axis)              # (L, 3)


def sample(edges: Edges, leds: list[Led], spread: float = 1.0) -> np.ndarray:
    """Colors (N, 3) float 0..255 for `leds`, in the same order.

    spread > 1 widens each LED's zone around its center (softer, blends
    neighbours); 1.0 = zones tile the edge exactly.
    """
    out = np.zeros((len(leds), 3), np.float32)
    by_side: dict[str, list[int]] = {}
    for i, led in enumerate(leds):
        by_side.setdefault(led.side, []).append(i)

    for side, idx in by_side.items():
        horizontal = side in ("top", "bottom")
        prof = _profile(edges.side(side), horizontal)
        n = prof.shape[0]
        if n == 0:
            continue
        cum = np.vstack([np.zeros((1, 3), np.float32), np.cumsum(prof, axis=0)])
        u0 = np.array([leds[i].u0 for i in idx], np.float32)
        u1 = np.array([leds[i].u1 for i in idx], np.float32)
        if spread != 1.0:
            c, half = (u0 + u1) / 2, (u1 - u0) * spread / 2
            u0, u1 = c - half, c + half
        a = np.clip(np.floor(u0 * n), 0, n - 1).astype(np.int64)
        b = np.clip(np.ceil(u1 * n), 1, n).astype(np.int64)
        b = np.maximum(b, a + 1)
        out[idx] = (cum[b] - cum[a]) / (b - a)[:, None]

    np.sqrt(out, out=out)                   # back from linear light
    return out


def saturate(colors: np.ndarray, amount: float) -> np.ndarray:
    """Push colors away from their own grey (amount 1.0 = unchanged)."""
    if amount == 1.0:
        return colors
    luma = (colors @ np.array([0.2126, 0.7152, 0.0722], np.float32))[:, None]
    return np.clip(luma + (colors - luma) * amount, 0, 255)


class Smoother:
    """Frame-rate independent exponential smoothing with a fast path for
    scene cuts, so the lights follow cuts quickly but don't flicker."""

    def __init__(self, time_constant: float = 0.08):
        self.tau = time_constant
        self._state: np.ndarray | None = None

    def reset(self) -> None:
        self._state = None

    def __call__(self, colors: np.ndarray, dt: float) -> np.ndarray:
        if self._state is None or self._state.shape != colors.shape or self.tau <= 0:
            self._state = colors.copy()
            return colors
        change = float(np.abs(colors - self._state).mean())
        tau = self.tau / 4 if change > 60 else self.tau
        k = 1.0 - np.exp(-max(dt, 0.0) / tau)
        self._state += (colors - self._state) * k
        return self._state.copy()
