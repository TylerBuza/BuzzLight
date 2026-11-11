"""Where each LED of the strip sits around the screen.

The strip is glued around the back of the monitor. It starts at one corner,
runs clockwise or counter-clockwise (as seen from the front), and may have a
few LEDs at its start that aren't on an edge (`offset`).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from buzzlight.device.protocol import LED_COUNT

SIDES = ("top", "right", "bottom", "left")
CORNERS = ("top-left", "top-right", "bottom-right", "bottom-left")

# Clockwise walk around the screen (front view), starting at the top-left.
# Each side is traversed in this direction; `u` (0..1) along a side is
# measured left→right for top/bottom and top→bottom for left/right.
_CW = ("top", "right", "bottom", "left")
_CW_FORWARD = {"top": True, "right": True, "bottom": False, "left": False}


@dataclass(frozen=True)
class Led:
    index: int          # position along the strip (0 = input end)
    side: str
    u0: float           # span along the side, 0..1 in that side's axis
    u1: float

    @property
    def u(self) -> float:
        return (self.u0 + self.u1) / 2


@dataclass
class Layout:
    top: int = 23
    right: int = 15
    bottom: int = 22
    left: int = 15
    start: str = "bottom-right"
    clockwise: bool = True
    offset: int = 0

    def __post_init__(self):
        self.validate()

    def count(self, side: str) -> int:
        return getattr(self, side)

    @property
    def total(self) -> int:
        return self.offset + sum(self.count(s) for s in SIDES)

    def validate(self) -> "Layout":
        for s in SIDES:
            setattr(self, s, max(0, int(self.count(s))))
        self.offset = max(0, int(self.offset))
        if self.start not in CORNERS:
            self.start = "bottom-right"
        self.clockwise = bool(self.clockwise)
        # Never address more LEDs than the controller has.
        over = self.total - LED_COUNT
        for s in ("bottom", "top", "left", "right"):
            if over <= 0:
                break
            cut = min(over, self.count(s))
            setattr(self, s, self.count(s) - cut)
            over -= cut
        if over > 0:
            self.offset = max(0, self.offset - over)
        return self

    def walk(self) -> list[tuple[str, bool]]:
        """Sides in strip order, with whether each is walked clockwise."""
        c = CORNERS.index(self.start)
        if self.clockwise:
            return [(_CW[(c + i) % 4], True) for i in range(4)]
        return [(_CW[(c - 1 - i) % 4], False) for i in range(4)]

    def leds(self) -> list[Led]:
        out: list[Led] = []
        i = self.offset
        for side, cw in self.walk():
            n = self.count(side)
            for k in range(n):
                a, b = k / n, (k + 1) / n
                if _CW_FORWARD[side] != cw:     # walking against the u axis
                    a, b = 1 - b, 1 - a
                out.append(Led(i, side, a, b))
                i += 1
        return out

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict | None) -> "Layout":
        known = {k: v for k, v in (d or {}).items()
                 if k in cls.__dataclass_fields__}
        return cls(**known).validate()


def identify_frame(layout: Layout) -> list[tuple[int, int, int]]:
    """A frame that paints each side its own color, with the first LED of
    the strip white, so a user can check the layout against reality."""
    colors = {"top": (0, 90, 255), "right": (255, 190, 0),
              "bottom": (255, 0, 40), "left": (0, 220, 60)}
    frame = [(0, 0, 0)] * LED_COUNT
    leds = layout.leds()
    for led in leds:
        frame[led.index] = colors[led.side]
    if leds:
        frame[leds[0].index] = (255, 255, 255)
    return frame
