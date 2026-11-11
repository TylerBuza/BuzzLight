import threading
import time
import unittest
from unittest import mock

import numpy as np

from buzzlight.ambilight import engine as eng
from buzzlight.ambilight import letterbox as lb
from buzzlight.ambilight.capture import Edges, Monitor, _slice
from buzzlight.ambilight.sampler import Smoother, sample, saturate
from buzzlight.layout import Layout, identify_frame

W, H = 3440, 1440


def screen(color=(200, 80, 40), bars=lb.NONE, w=W, h=H):
    img = np.zeros((h, w, 3), np.uint8)
    img[bars.top:h - bars.bottom, bars.left:w - bars.right] = color
    return img


class TestLayout(unittest.TestCase):
    def test_default_fits_controller(self):
        lay = Layout()
        self.assertLessEqual(lay.total, 75)
        self.assertEqual(len(lay.leds()), lay.total)

    def test_clockwise_from_bottom_right(self):
        leds = Layout(top=2, right=2, bottom=2, left=2).leds()
        self.assertEqual([l.side for l in leds],
                         ["bottom"] * 2 + ["left"] * 2 + ["top"] * 2 + ["right"] * 2)
        # bottom is walked right→left, left bottom→top, top left→right
        self.assertGreater(leds[0].u, leds[1].u)
        self.assertGreater(leds[2].u, leds[3].u)
        self.assertLess(leds[4].u, leds[5].u)
        self.assertLess(leds[6].u, leds[7].u)

    def test_counter_clockwise_from_bottom_right(self):
        leds = Layout(top=2, right=2, bottom=2, left=2, clockwise=False).leds()
        self.assertEqual([l.side for l in leds][::2], ["right", "top", "left", "bottom"])
        self.assertGreater(leds[0].u, leds[1].u)   # right walked bottom→top
        self.assertGreater(leds[2].u, leds[3].u)   # top walked right→left

    def test_offset_and_indices(self):
        leds = Layout(top=3, right=0, bottom=0, left=0, start="top-left", offset=4).leds()
        self.assertEqual([l.index for l in leds], [4, 5, 6])
        self.assertAlmostEqual(leds[0].u0, 0.0)
        self.assertAlmostEqual(leds[-1].u1, 1.0)

    def test_validate_caps_total(self):
        lay = Layout(top=40, right=30, bottom=40, left=30, offset=5).validate()
        self.assertEqual(lay.total, 75)

    def test_roundtrip_and_bad_values(self):
        lay = Layout.from_dict({"top": "10", "start": "nowhere", "junk": 1})
        self.assertEqual(lay.top, 10)
        self.assertEqual(lay.start, "bottom-right")
        self.assertEqual(Layout.from_dict(lay.to_dict()), lay)

    def test_identify_marks_first_led_white(self):
        lay = Layout(offset=2)
        f = identify_frame(lay)
        self.assertEqual(f[0], (0, 0, 0))
        self.assertEqual(f[2], (255, 255, 255))


class TestSampler(unittest.TestCase):
    def test_uniform_screen(self):
        e = _slice(screen((10, 120, 250)), 100)
        got = sample(e, Layout().leds())
        np.testing.assert_allclose(got, np.tile([10, 120, 250], (len(got), 1)), atol=0.6)

    def test_left_half_red_right_half_blue(self):
        img = np.zeros((H, W, 3), np.uint8)
        img[:, : W // 2] = (255, 0, 0)
        img[:, W // 2:] = (0, 0, 255)
        leds = Layout().leds()
        got = sample(_slice(img, 100), leds)
        for led, c in zip(leds, got):
            if led.side == "left":
                self.assertGreater(c[0], 250)
            if led.side == "right":
                self.assertGreater(c[2], 250)

    def test_linear_light_average(self):
        img = np.zeros((100, 100, 3), np.uint8)
        img[:, ::2] = 255                      # half white, half black
        got = sample(_slice(img, 10), Layout(top=1, right=0, bottom=0, left=0,
                                               start="top-left").leds())
        self.assertGreater(got[0][0], 170)       # sqrt(0.5)*255 ≈ 180, not 128

    def test_saturate(self):
        c = np.array([[200, 100, 100]], np.float32)
        self.assertGreater(saturate(c, 1.5)[0][0] - saturate(c, 1.5)[0][1], 100)
        np.testing.assert_array_equal(saturate(c, 1.0), c)

    def test_smoother_dt_independent(self):
        a, b = Smoother(0.1), Smoother(0.1)
        target = np.array([[50.0, 50, 50]], np.float32)
        a(np.zeros((1, 3), np.float32), 0); b(np.zeros((1, 3), np.float32), 0)
        for _ in range(10):
            ra = a(target, 0.01)
        rb = b(target, 0.1)
        np.testing.assert_allclose(ra, rb, rtol=1e-4)


def edges_of(img, depth):
    return _slice(img, depth)


class TestLetterbox(unittest.TestCase):
    def probe(self, img):
        return edges_of(img, lb.probe_depth(W, H))

    def test_none(self):
        self.assertEqual(lb.measure(self.probe(screen())), (0, 0))

    def test_ultrawide_pillarbox(self):
        horiz, vert = lb.measure(self.probe(screen(bars=lb.Bars(440, 0, 440, 0))))
        self.assertAlmostEqual(horiz, 440, delta=4)
        self.assertEqual(vert, 0)

    def test_letterbox_with_subtitles(self):
        img = screen(bars=lb.Bars(0, 180, 0, 180))
        img[H - 120:H - 90, 1400:2000] = 255
        self.assertAlmostEqual(lb.measure(self.probe(img))[1], 180, delta=4)

    def test_dark_scene_unknown(self):
        self.assertEqual(lb.measure(self.probe(screen((5, 5, 5)))), (None, None))

    def test_one_sided_dark_panel(self):
        img = screen()
        img[:, :500] = 0
        self.assertEqual(lb.measure(self.probe(img))[0], 0)

    def test_noise_in_bars(self):
        img = screen(bars=lb.Bars(440, 0, 440, 0))
        img = np.maximum(img, np.random.default_rng(1).integers(0, 20, img.shape, dtype=np.uint8))
        self.assertAlmostEqual(lb.measure(self.probe(img))[0], 440, delta=4)

    def test_tracker_debounce(self):
        t = lb.Tracker(confirm=2)
        self.assertEqual(t.update(440, 0, W, H), lb.NONE)
        self.assertEqual(t.update(442, 0, W, H).left, 442)
        self.assertEqual(t.update(None, None, W, H).left, 442)
        t.update(0, 0, W, H)
        self.assertEqual(t.bars.left, 442)          # one blip doesn't apply
        self.assertEqual(t.update(0, 0, W, H), lb.NONE)

    def test_crop_reaches_picture(self):
        bars = lb.Bars(440, 0, 440, 0)
        img = screen((200, 80, 40), bars)
        e = lb.crop(edges_of(img, lb.capture_depths(bars, 115)), bars, 115)
        self.assertEqual((e.width, e.height), (W - 880, H))
        for s in ("top", "right", "bottom", "left"):
            self.assertTrue((e.side(s) == (200, 80, 40)).all(), s)


class FakeCapture:
    name = "fake"

    def __init__(self, img):
        self.img = img

    @property
    def size(self):
        return self.img.shape[1], self.img.shape[0]

    def grab(self, depth):
        return _slice(self.img, depth)

    def close(self):
        pass


class FakeStrip:
    def __init__(self):
        self.frames = []
        self.lock = threading.Lock()

    def set_frame(self, f):
        with self.lock:
            self.frames.append(f)


class TestEngine(unittest.TestCase):
    def run_engine(self, img, seconds=0.5, **cfg):
        strip = FakeStrip()
        cap = FakeCapture(img)
        mon = [Monitor(1, 0, 0, img.shape[1], img.shape[0])]
        with mock.patch.object(eng, "list_monitors", lambda: mon), \
                mock.patch.object(eng, "open_capture", lambda m, p: cap):
            a = eng.Ambilight(strip, eng.AmbilightConfig(smoothing=0, saturation=1.0, **cfg))
            a.start()
            time.sleep(seconds)
            a.stop()
        return a, strip, cap

    def test_frames_flow_and_layout_mapping(self):
        a, strip, _ = self.run_engine(screen((0, 255, 0)))
        self.assertGreater(len(strip.frames), 5)
        lay = Layout()
        f = strip.frames[-1]
        self.assertEqual(len(f), 75)
        for led in lay.leds():
            self.assertEqual(f[led.index], (0, 255, 0))
        self.assertEqual(a.stats.error, "")

    def test_pillarbox_sides_follow_picture(self):
        a, strip, _ = self.run_engine(screen((0, 0, 255), lb.Bars(440, 0, 440, 0)), 1.2)
        self.assertAlmostEqual(a.stats.bars.left, 440, delta=4)
        f = strip.frames[-1]
        for led in Layout().leds():
            self.assertEqual(f[led.index], (0, 0, 255), led)

    def test_black_bars_off(self):
        a, strip, _ = self.run_engine(screen((0, 0, 255), lb.Bars(440, 0, 440, 0)), 0.8,
                                      black_bars=False)
        self.assertEqual(a.stats.bars, lb.NONE)
        side = [strip.frames[-1][l.index] for l in Layout().leds() if l.side == "left"]
        self.assertTrue(all(c == (0, 0, 0) for c in side))

    def test_capture_error_recovers(self):
        strip = FakeStrip()
        img = screen()
        calls = {"n": 0}

        class Flaky(FakeCapture):
            def grab(self, depth):
                calls["n"] += 1
                if calls["n"] == 3:
                    raise RuntimeError("display changed")
                return super().grab(depth)

        mon = [Monitor(1, 0, 0, W, H)]
        with mock.patch.object(eng, "list_monitors", lambda: mon), \
                mock.patch.object(eng, "open_capture", lambda m, p: Flaky(img)):
            a = eng.Ambilight(strip, eng.AmbilightConfig(black_bars=False))
            a.start()
            time.sleep(1.6)
            a.stop()
        self.assertGreater(calls["n"], 4)

    def test_config_roundtrip(self):
        c = eng.AmbilightConfig(fps=30, layout=Layout(top=10))
        self.assertEqual(eng.AmbilightConfig.from_dict(c.to_dict()), c)


if __name__ == "__main__":
    unittest.main()
