import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

from buzzlight import autostart
from buzzlight.ambilight.engine import AmbilightConfig
from buzzlight.controller import Controller
from buzzlight.layout import Layout
from buzzlight.settings import Settings, load, save


class FakeStrip:
    def __init__(self):
        self.calls = []
        self.connected = False
        self.port = None
        self.on_status = None

    def __getattr__(self, name):
        if name.startswith("set_") or name in ("start", "stop"):
            return lambda *a, **k: self.calls.append((name, a, k))
        raise AttributeError(name)


class FakeAmbilight:
    def __init__(self):
        self.running = False
        self.configured = {}

    def start(self):
        self.running = True

    def stop(self):
        self.running = False

    def configure(self, **kw):
        self.configured.update(kw)


def make(settings=None):
    saved = []
    c = Controller(strip=FakeStrip(), settings=settings or Settings(),
                   save=lambda s: saved.append(s.to_dict()))
    c.ambilight = FakeAmbilight()
    return c, saved


class TestController(unittest.TestCase):
    def test_start_restores_color_mode(self):
        c, _ = make(Settings(color=(1, 2, 3), brightness=90))
        c.start()
        names = [x[0] for x in c.strip.calls]
        self.assertIn(("set_brightness", (90,), {}), c.strip.calls)
        self.assertIn(("set_color", ((1, 2, 3),), {}), c.strip.calls)
        self.assertIn("start", names)
        self.assertFalse(c.ambilight.running)

    def test_ambilight_mode_and_back(self):
        c, _ = make()
        c.start()
        c.set_mode("ambilight")
        self.assertTrue(c.ambilight.running)
        c.set_color((9, 9, 9))
        self.assertFalse(c.ambilight.running)
        self.assertEqual(c.settings.mode, "color")

    def test_power_off_stops_ambilight_and_on_resumes(self):
        c, _ = make(Settings(mode="ambilight"))
        c.start()
        self.assertTrue(c.ambilight.running)
        c.set_power(False)
        self.assertFalse(c.ambilight.running)
        c.set_power(True)
        self.assertTrue(c.ambilight.running)

    def test_choosing_mode_turns_power_on(self):
        c, _ = make(Settings(power=False))
        c.set_mode("color")
        self.assertTrue(c.settings.power)

    def test_saves_are_debounced(self):
        c, saved = make()
        c.SAVE_DELAY = 0.1
        for b in range(10):
            c.set_brightness(b * 10)
        time.sleep(0.4)
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["brightness"], 90)

    def test_identify_then_restore(self):
        c, _ = make(Settings(mode="ambilight"))
        c.start()
        c.identify(seconds=0.1)
        self.assertTrue(c.identifying)
        self.assertFalse(c.ambilight.running)
        self.assertEqual(c.strip.calls[-1][0], "set_frame")
        time.sleep(0.3)
        self.assertFalse(c.identifying)
        self.assertTrue(c.ambilight.running)

    def test_layout_change_reaches_engine(self):
        c, _ = make()
        c.set_layout(Layout(top=5, right=5, bottom=5, left=5))
        self.assertEqual(c.ambilight.configured["layout"].top, 5)
        self.assertEqual(c.settings.ambilight.layout.top, 5)


class TestSettings(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.json")
            s = Settings(power=False, brightness=33, mode="ambilight", color=(1, 2, 3),
                         ambilight=AmbilightConfig(fps=30, layout=Layout(top=7)))
            save(s, p)
            self.assertEqual(load(p).to_dict(), s.to_dict())

    def test_missing_and_corrupt_files_give_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.json")
            self.assertEqual(load(p).to_dict(), Settings().to_dict())
            with open(p, "w") as f:
                f.write("{not json")
            self.assertEqual(load(p).to_dict(), Settings().to_dict())

    def test_bad_values_are_clamped_or_ignored(self):
        s = Settings.from_dict({"brightness": 999, "mode": "disco", "color": [300, -1, 5]})
        self.assertEqual(s.brightness, 255)
        self.assertEqual(s.mode, "color")
        self.assertEqual(s.color, (255, 0, 5))

    def test_save_is_atomic_json(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.json")
            save(Settings(), p)
            with open(p) as f:
                json.load(f)
            self.assertEqual(os.listdir(d), ["s.json"])


class TestAutostart(unittest.TestCase):
    def test_source_command_uses_pythonw_launcher(self):
        with tempfile.TemporaryDirectory() as d:
            py, pyw = os.path.join(d, "python.exe"), os.path.join(d, "pythonw.exe")
            for f in (py, pyw):
                open(f, "w").close()
            with mock.patch.object(sys, "executable", py):
                self.assertEqual(autostart.command(),
                                 f'"{pyw}" "{autostart.LAUNCHER}" --minimized')

    def test_frozen_command(self):
        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.object(sys, "executable", r"C:\Apps\BuzzLight.exe"):
            self.assertEqual(autostart.command(), r'"C:\Apps\BuzzLight.exe" --minimized')

    def test_launcher_exists(self):
        self.assertTrue(os.path.exists(autostart.LAUNCHER))


if __name__ == "__main__":
    unittest.main()
