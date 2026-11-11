"""Where BuzzLight keeps its files."""

from __future__ import annotations

import os
import sys

APP_NAME = "BuzzLight"


def config_dir() -> str:
    if sys.platform == "win32":
        base = os.getenv("APPDATA") or os.path.expanduser("~")
        path = os.path.join(base, APP_NAME)
    else:
        path = os.path.join(os.path.expanduser("~"), ".config", "buzzlight")
    os.makedirs(path, exist_ok=True)
    return path


def settings_file() -> str:
    return os.path.join(config_dir(), "settings.json")


def log_file() -> str:
    return os.path.join(config_dir(), "buzzlight.log")


def resource(*parts: str) -> str:
    """Path to a bundled file, both from source and in a PyInstaller build."""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    if getattr(sys, "_MEIPASS", None):
        base = os.path.join(base, "buzzlight")
    return os.path.join(base, *parts)
