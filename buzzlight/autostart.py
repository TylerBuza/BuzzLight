"""'Start with Windows' via the per-user Run registry key (no admin)."""

from __future__ import annotations

import os
import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "BuzzLight"
LAUNCHER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "BuzzLight.pyw")


def supported() -> bool:
    return sys.platform == "win32"


def command() -> str:
    if getattr(sys, "frozen", False):           # PyInstaller build
        return f'"{sys.executable}" --minimized'
    exe = sys.executable
    d, name = os.path.split(exe)
    if name.lower() == "python.exe" and os.path.exists(os.path.join(d, "pythonw.exe")):
        exe = os.path.join(d, "pythonw.exe")    # no console window at login
    return f'"{exe}" "{LAUNCHER}" --minimized'


def _key(access):
    import winreg
    return winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, access)


def current() -> str | None:
    if not supported():
        return None
    import winreg
    try:
        with _key(winreg.KEY_READ) as k:
            return winreg.QueryValueEx(k, VALUE_NAME)[0]
    except OSError:
        return None


def enabled() -> bool:
    return current() is not None


def set_enabled(on: bool) -> None:
    if not supported():
        raise OSError("Start with Windows is only available on Windows")
    import winreg
    with _key(winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, VALUE_NAME, 0, winreg.REG_SZ, command())
        else:
            try:
                winreg.DeleteValue(k, VALUE_NAME)
            except FileNotFoundError:
                pass


def repair() -> None:
    """Point an existing entry at this install if BuzzLight moved."""
    cur = current()
    if cur is not None and cur != command():
        try:
            set_enabled(True)
        except OSError:
            pass
