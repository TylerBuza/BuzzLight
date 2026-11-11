"""Packet encoder/decoder for the Lytmi/Beelight USB LED controller.

See docs/PROTOCOL.md for the wire format. Every builder returns a complete,
ready-to-write frame.
"""

from __future__ import annotations

import os
from typing import Sequence

MAGIC = b"\x55\xaa\x5a"
KEY_LEN_XOR = 0x31
KEY_LEN_RANGE = (3, 10)
LED_COUNT = 75

# ctrl codes inside a `00 05` control message
CTRL_POWER = 0x01
CTRL_BRIGHTNESS = 0x02
CTRL_COLOR = 0x04
CTRL_FRAME = 0x05
CTRL_WORK_MODE = 0x06
WORK_MODE_PC = 0

DIMMER_MAX = 1000

RGB = tuple[int, int, int]


class ProtocolError(ValueError):
    pass


def _u8(v) -> int:
    return 0 if v < 0 else 255 if v > 255 else int(v)


# --- framing -----------------------------------------------------------------

def encode(plain: bytes, key: bytes | None = None) -> bytes:
    """Obfuscate `plain` (attr + cmd + data) and wrap it in a frame."""
    if key is None:
        lo, hi = KEY_LEN_RANGE
        key = os.urandom(lo + os.urandom(1)[0] % (hi - lo + 1))
    n = len(key)
    if not 2 <= n <= 255:
        raise ProtocolError("key length out of range")
    body = bytearray(2 + n + len(plain))
    body[1] = n ^ KEY_LEN_XOR
    body[2:2 + n] = key
    body[2 + n:] = bytes(b ^ key[i % n] for i, b in enumerate(plain))
    body[0] = sum(body[1:]) & 0xFF
    return MAGIC + len(body).to_bytes(2, "little") + bytes(body)


def decode(packet: bytes) -> bytes:
    """Inverse of encode(): validate a full frame and return `plain`."""
    if len(packet) < 8 or packet[:3] != MAGIC:
        raise ProtocolError("not a frame")
    length = int.from_bytes(packet[3:5], "little")
    body = packet[5:5 + length]
    if len(body) != length:
        raise ProtocolError("truncated frame")
    if body[0] != sum(body[1:]) & 0xFF:
        raise ProtocolError("bad checksum")
    n = body[1] ^ KEY_LEN_XOR
    if n < 2 or 2 + n > len(body):
        raise ProtocolError("bad key length")
    key = body[2:2 + n]
    return bytes(b ^ key[i % n] for i, b in enumerate(body[2 + n:]))


def _control(ctrl: int, payload: bytes) -> bytes:
    return encode(bytes([0x00, 0x05, ctrl, 0xFF])
                  + len(payload).to_bytes(2, "little") + payload)


# --- messages ----------------------------------------------------------------

def heartbeat() -> bytes:
    return encode(b"\x01\x00")


def query(kind: int) -> bytes:
    """kind: 1 device info, 2 channels, 3 capabilities."""
    return encode(bytes([0x00, kind]))


def power(on: bool) -> bytes:
    return _control(CTRL_POWER, b"\x01" if on else b"\x00")


def dimmer(level: int) -> bytes:
    """Hardware dimmer, 0..1000."""
    level = max(0, min(DIMMER_MAX, int(level)))
    return _control(CTRL_BRIGHTNESS, level.to_bytes(2, "little"))


def brightness(value: int) -> bytes:
    """UI brightness 0..255 mapped onto the dimmer."""
    return dimmer(round(_u8(value) * DIMMER_MAX / 255))


def solid(color: RGB) -> bytes:
    return _control(CTRL_COLOR, bytes(_u8(c) for c in color))


def frame(colors: Sequence[RGB]) -> bytes:
    """Per-LED frame. colors[0] is the first LED from the strip's input end;
    the wire order (far end first) is handled here."""
    led = bytearray(LED_COUNT * 3)
    count = min(len(colors), LED_COUNT)
    for i in range(count):
        r, g, b = colors[i]
        j = (LED_COUNT - 1 - i) * 3
        led[j] = _u8(r)
        led[j + 1] = _u8(g)
        led[j + 2] = _u8(b)
    return _control(CTRL_FRAME, LED_COUNT.to_bytes(2, "little") + bytes(led))


def work_mode(mode: int = WORK_MODE_PC) -> bytes:
    return _control(CTRL_WORK_MODE, bytes([mode & 0xFF, 0, 0]))


def wake_sequence() -> list[bytes]:
    return [query(1), query(2), power(True), query(3),
            heartbeat(), heartbeat(), heartbeat()]


def frame_colors(packet: bytes) -> list[RGB]:
    """Decode a per-LED frame back to colors in strip order (for tests)."""
    plain = decode(packet)
    if plain[:3] != bytes([0x00, 0x05, CTRL_FRAME]):
        raise ProtocolError("not a frame packet")
    data = plain[8:8 + LED_COUNT * 3]
    wire = [tuple(data[i:i + 3]) for i in range(0, len(data), 3)]
    return list(reversed(wire))
