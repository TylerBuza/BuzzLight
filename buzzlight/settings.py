"""User settings, stored as JSON in the config folder."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field

from buzzlight.ambilight.engine import AmbilightConfig
from buzzlight.paths import settings_file

MODES = ("color", "ambilight")


@dataclass
class Settings:
    power: bool = True
    brightness: int = 200
    mode: str = "color"
    color: tuple[int, int, int] = (255, 120, 40)
    ambilight: AmbilightConfig = field(default_factory=AmbilightConfig)

    def to_dict(self) -> dict:
        return {"power": self.power, "brightness": self.brightness,
                "mode": self.mode, "color": list(self.color),
                "ambilight": self.ambilight.to_dict()}

    @classmethod
    def from_dict(cls, d: dict) -> "Settings":
        s = cls()
        if not isinstance(d, dict):
            return s
        try:
            s.power = bool(d.get("power", s.power))
            s.brightness = max(0, min(255, int(d.get("brightness", s.brightness))))
            if d.get("mode") in MODES:
                s.mode = d["mode"]
            c = d.get("color")
            if isinstance(c, (list, tuple)) and len(c) == 3:
                s.color = tuple(max(0, min(255, int(v))) for v in c)
            s.ambilight = AmbilightConfig.from_dict(d.get("ambilight"))
        except (TypeError, ValueError) as e:
            print(f"[settings] ignoring invalid settings: {e}")
        return s


def load(path: str | None = None) -> Settings:
    path = path or settings_file()
    try:
        with open(path, encoding="utf-8") as f:
            return Settings.from_dict(json.load(f))
    except FileNotFoundError:
        return Settings()
    except (OSError, ValueError) as e:
        print(f"[settings] could not read {path}: {e}")
        return Settings()


def save(settings: Settings, path: str | None = None) -> None:
    """Atomic write: a crash mid-save never leaves a broken file."""
    path = path or settings_file()
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(prefix=".settings-", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(settings.to_dict(), f, indent=2)
        os.replace(tmp, path)
    except OSError as e:
        print(f"[settings] could not save: {e}")
        try:
            os.unlink(tmp)
        except OSError:
            pass

