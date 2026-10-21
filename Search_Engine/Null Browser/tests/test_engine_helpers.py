"""Chromium flags and codec report helpers."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from null_browser.engine import codecs, flags


def settings(**kw):
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(kw, f); f.close()
    return f.name


class FlagTests(unittest.TestCase):
    def test_default_uses_gpu_rasterization(self):
        fl, _ = flags.build(settings())
        self.assertIn("--enable-gpu-rasterization", fl)
        self.assertNotIn("--disable-gpu", fl)

    def test_safe_mode_disables_gpu(self):
        fl, _ = flags.build(settings(), safe=True)
        self.assertIn("--disable-gpu", fl)
        self.assertNotIn("--enable-gpu-rasterization", fl)

    def test_hardware_acceleration_off(self):
        fl, _ = flags.build(settings(hardware_acceleration=False))
        self.assertIn("--disable-gpu", fl)

    def test_missing_settings_file(self):
        fl, data = flags.build("/nonexistent/settings.json")
        self.assertEqual(data, {})
        self.assertTrue(fl)


class CodecTests(unittest.TestCase):
    def test_lacks_h264(self):
        self.assertFalse(codecs.lacks_h264(None))
        self.assertTrue(codecs.lacks_h264({"h264": False}))
        self.assertFalse(codecs.lacks_h264({"h264": True}))


if __name__ == "__main__":
    unittest.main()
