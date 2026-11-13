"""Offline unit tests for the pure signal helpers in scanner.py (no network).
Run from the repo root:  python -m unittest discover tests -v"""
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scanner


def candle(o, h, l, c, v=100.0):
    return dict(o=o, h=h, l=l, c=c, v=v)


class TestFmt(unittest.TestCase):
    def test_precision_by_price(self):
        self.assertEqual(scanner.fmt(12345.678), "12345.68")
        self.assertEqual(scanner.fmt(55.5), "55.500")
        self.assertEqual(scanner.fmt(2.5), "2.5000")
        self.assertEqual(scanner.fmt(0.05), "0.05000")


class TestRR(unittest.TestCase):
    def test_reward_to_risk(self):
        o = {"zone": {"entry": 100, "stop": 95}, "target": 115}
        self.assertAlmostEqual(scanner.rr_of(o), 3.0)

    def test_invalid_inputs_return_none(self):
        self.assertIsNone(scanner.rr_of({"zone": None, "target": 10}))
        self.assertIsNone(scanner.rr_of({"zone": {"entry": 100, "stop": 95}, "target": None}))
        self.assertIsNone(scanner.rr_of({"zone": {"entry": 95, "stop": 100}, "target": 120}))  # stop above entry


class TestRSI(unittest.TestCase):
    def test_short_series_is_neutral(self):
        self.assertEqual(scanner.rsi14([candle(1, 1, 1, 1)] * 10), 50.0)

    def test_always_rising_is_100(self):
        d = [candle(i, i, i, i) for i in range(1, 60)]
        self.assertEqual(scanner.rsi14(d), 100.0)

    def test_always_falling_is_near_0(self):
        d = [candle(i, i, i, i) for i in range(100, 40, -1)]
        self.assertLess(scanner.rsi14(d), 1.0)


class TestZones(unittest.TestCase):
    def test_finds_repeated_support(self):
        # zig-zag that repeatedly bottoms near 100
        d = []
        for i in range(120):
            base = 100 if (i // 6) % 2 == 0 else 110
            low = 100 if i % 12 == 6 else base + 1
            d.append(candle(base + 2, base + 4, low, base + 3))
        lv, last, atr, tol = scanner.zones(d)
        self.assertTrue(lv)
        self.assertTrue(any(abs(x["p"] - 100) < 3 for x in lv))
        self.assertGreater(atr, 0)


class TestStateFiles(unittest.TestCase):
    def test_missing_file_returns_empty(self):
        self.assertEqual(scanner.load("/nonexistent/path.json"), {})

    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as t:
            p = os.path.join(t, "s.json")
            scanner.save(p, {"a": 1})
            self.assertEqual(scanner.load(p), {"a": 1})

    def test_corrupt_file_warns_and_returns_empty(self):
        with tempfile.TemporaryDirectory() as t:
            p = os.path.join(t, "bad.json")
            with open(p, "w") as f: f.write("{not json")
            self.assertEqual(scanner.load(p), {})


if __name__ == "__main__":
    unittest.main()
