"""Locate the LED controller's serial port."""

from __future__ import annotations

import os

from serial.tools import list_ports

CONTROLLER_VID = 0x2E3C
CONTROLLER_PID = 0x5740


def find_controller() -> str | None:
    """Port of the first attached controller, or None.

    BUZZLIGHT_PORT overrides detection. Only the controller's exact USB ID
    is accepted, so LED packets never go to some other serial device.
    """
    forced = os.getenv("BUZZLIGHT_PORT")
    if forced:
        return forced
    try:
        for p in list_ports.comports():
            if p.vid == CONTROLLER_VID and p.pid == CONTROLLER_PID:
                return p.device
    except Exception:
        pass
    return None


def port_present(name: str) -> bool:
    try:
        return any(p.device == name for p in list_ports.comports())
    except Exception:
        return False
