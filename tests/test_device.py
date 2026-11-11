import threading
import time
import unittest

from buzzlight.device import protocol as p
from buzzlight.device.strip import Strip


class TestProtocol(unittest.TestCase):
    def test_roundtrip_any_key_length(self):
        for n in range(2, 12):
            plain = b"\x00\x05\x04\xff\x03\x00\x10\x20\x30"
            self.assertEqual(p.decode(p.encode(plain, key=bytes(range(1, n + 1)))), plain)

    def test_known_layout(self):
        pkt = p.encode(b"\x01\x00", key=b"\xaa\xbb\xcc")
        self.assertEqual(pkt[:3], b"\x55\xaa\x5a")
        self.assertEqual(int.from_bytes(pkt[3:5], "little"), 2 + 3 + 2)
        body = pkt[5:]
        self.assertEqual(body[1], 3 ^ 0x31)
        self.assertEqual(body[2:5], b"\xaa\xbb\xcc")
        self.assertEqual(body[5:], bytes([0x01 ^ 0xaa, 0x00 ^ 0xbb]))
        self.assertEqual(body[0], sum(body[1:]) & 0xFF)

    def test_random_keys_in_range(self):
        for _ in range(200):
            n = p.encode(b"\x01\x00")[6] ^ 0x31
            self.assertTrue(3 <= n <= 10)

    def test_bad_checksum_rejected(self):
        pkt = bytearray(p.heartbeat())
        pkt[5] ^= 0xFF
        with self.assertRaises(p.ProtocolError):
            p.decode(bytes(pkt))

    def test_messages(self):
        self.assertEqual(p.decode(p.heartbeat()), b"\x01\x00")
        self.assertEqual(p.decode(p.power(True)), b"\x00\x05\x01\xff\x01\x00\x01")
        self.assertEqual(p.decode(p.power(False)), b"\x00\x05\x01\xff\x01\x00\x00")
        self.assertEqual(p.decode(p.solid((300, -5, 7))), b"\x00\x05\x04\xff\x03\x00\xff\x00\x07")
        self.assertEqual(p.decode(p.work_mode()), b"\x00\x05\x06\xff\x03\x00\x00\x00\x00")
        self.assertEqual(p.decode(p.brightness(255))[-2:], (1000).to_bytes(2, "little"))
        self.assertEqual(p.decode(p.brightness(0))[-2:], b"\x00\x00")
        self.assertEqual(p.decode(p.dimmer(5000))[-2:], (1000).to_bytes(2, "little"))

    def test_frame_header_and_reversed_order(self):
        colors = [(i, 2 * i, 3 * i) for i in range(75)]
        plain = p.decode(p.frame(colors))
        self.assertEqual(plain[:8], b"\x00\x05\x05\xff\xe3\x00\x4b\x00")
        self.assertEqual(len(plain), 8 + 225)
        self.assertEqual(tuple(plain[8:11]), colors[74])   # far end first
        self.assertEqual(tuple(plain[-3:]), colors[0])
        self.assertEqual(p.frame_colors(p.frame(colors)), colors)

    def test_short_frame_padded_black(self):
        got = p.frame_colors(p.frame([(9, 9, 9)] * 10))
        self.assertEqual(got[:10], [(9, 9, 9)] * 10)
        self.assertEqual(got[10:], [(0, 0, 0)] * 65)


class FakeSerial:
    """Records decoded packets; can be told to start failing."""

    def __init__(self, **kw):
        self.kw = kw
        self.sent = []
        self.fail = False
        self.closed = False
        self.in_waiting = 0
        self.lock = threading.Lock()

    def write(self, data):
        if self.fail:
            raise OSError("device gone")
        with self.lock:
            self.sent.append(p.decode(data))

    def read(self, n):
        return b""

    def close(self):
        self.closed = True

    def packets(self):
        with self.lock:
            return list(self.sent)


def ctrl(plain):
    """ctrl code of a control message, else None."""
    return plain[2] if len(plain) > 2 and plain[:2] == b"\x00\x05" else None


def wait_for(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


class TestStrip(unittest.TestCase):
    def setUp(self):
        self.ports = []

        def opener(**kw):
            s = FakeSerial(**kw)
            self.ports.append(s)
            return s

        self.strip = Strip(port="COM_TEST", opener=opener)
        self.events = []
        self.strip.on_status = lambda c, port: self.events.append((c, port))

    def tearDown(self):
        self.strip.stop()

    def test_handshake_then_color(self):
        self.strip.set_color((10, 20, 30))
        self.strip.start()
        self.assertTrue(wait_for(lambda: self.strip.connected))
        ser = self.ports[0]
        self.assertEqual(ser.kw["baudrate"], 500_000)
        pk = ser.packets()
        # wake sequence, then dim to zero before power on, then PC mode
        self.assertEqual(pk[0], b"\x00\x01")
        i = pk.index(b"\x00\x05\x06\xff\x03\x00\x00\x00\x00")
        self.assertEqual(pk[i - 3][2], p.CTRL_BRIGHTNESS)
        self.assertEqual(pk[i - 3][-2:], b"\x00\x00")
        solid = b"\x00\x05\x04\xff\x03\x00\x0a\x14\x1e"
        self.assertTrue(wait_for(lambda: solid in ser.packets()))
        self.assertEqual(self.events[0], (True, "COM_TEST"))

    def test_heartbeats_and_refresh_while_idle(self):
        self.strip.set_color((1, 2, 3))
        self.strip.start()
        self.assertTrue(wait_for(lambda: self.strip.connected))
        ser = self.ports[0]
        n0 = len(ser.packets())
        time.sleep(1.2)
        new = ser.packets()[n0:]
        self.assertGreaterEqual(new.count(b"\x01\x00"), 5)
        self.assertGreaterEqual(sum(1 for x in new if ctrl(x) == p.CTRL_COLOR), 2)
        self.assertLess(len(new), 60)  # idle: no busy-looping

    def test_frames_sent_latest_only(self):
        self.strip.start()
        self.assertTrue(wait_for(lambda: self.strip.connected))
        for v in range(50):
            self.strip.set_frame([(v, v, v)] * 75)
        last = p.frame(((49, 49, 49),) * 75)
        self.assertTrue(wait_for(
            lambda: p.decode(last) in self.ports[0].packets()))
        frames = [x for x in self.ports[0].packets() if ctrl(x) == p.CTRL_FRAME]
        self.assertLess(len(frames), 50)

    def test_fade_passes_through_intermediate_colors(self):
        self.strip.set_color((0, 0, 0))
        self.strip.start()
        self.assertTrue(wait_for(lambda: self.strip.connected))
        time.sleep(0.1)
        self.strip.set_color((200, 0, 0))
        target = b"\x00\x05\x04\xff\x03\x00\xc8\x00\x00"
        self.assertTrue(wait_for(lambda: target in self.ports[0].packets()))
        reds = {x[6] for x in self.ports[0].packets() if ctrl(x) == p.CTRL_COLOR}
        self.assertTrue(any(0 < r < 200 for r in reds))

    def test_power_off_stops_content(self):
        self.strip.set_color((5, 5, 5))
        self.strip.start()
        self.assertTrue(wait_for(lambda: self.strip.connected))
        self.strip.set_power(False)
        off = b"\x00\x05\x01\xff\x01\x00\x00"
        self.assertTrue(wait_for(lambda: off in self.ports[0].packets()))
        n = len(self.ports[0].packets())
        time.sleep(0.6)
        after = self.ports[0].packets()[n:]
        self.assertFalse(any(ctrl(x) == p.CTRL_COLOR for x in after))

    def test_reconnects_after_unplug(self):
        self.strip.set_color((5, 5, 5))
        self.strip.start()
        self.assertTrue(wait_for(lambda: self.strip.connected))
        self.ports[0].fail = True
        self.assertTrue(wait_for(lambda: not self.strip.connected))
        self.assertTrue(self.ports[0].closed)
        self.assertTrue(wait_for(lambda: len(self.ports) == 2 and self.strip.connected, 5))
        self.assertEqual([e[0] for e in self.events], [True, False, True])


if __name__ == "__main__":
    unittest.main()
