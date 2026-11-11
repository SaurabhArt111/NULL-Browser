import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from null_browser.core import paths, sitebg  # noqa: E402
from null_browser.engine import flags  # noqa: E402


def build(**settings):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "settings.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(settings, f)
        return flags.build(p)[0]


class FlagTests(unittest.TestCase):
    def test_preload_is_on_by_default_but_nothing_else_is_shared(self):
        f = build()
        self.assertNotIn("--dns-prefetch-disable", f)
        self.assertIn("--disable-background-networking", f)
        self.assertIn("--disable-component-update", f)
        self.assertTrue(any(x.startswith("--disable-features=") and "BrowsingTopics" in x for x in f))
        self.assertFalse(any(x.startswith("--disable-features=") and "NetworkPrediction" in x for x in f))

    def test_preload_can_be_turned_off(self):
        f = build(preload_pages=False)
        self.assertIn("--dns-prefetch-disable", f)
        self.assertTrue(any(x.startswith("--disable-features=") and "NetworkPrediction" in x for x in f))

    def test_single_disable_features_switch(self):
        self.assertEqual(len([x for x in build() if x.startswith("--disable-features=")]), 1)


class SiteColourTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._orig = paths.data_dir
        paths.data_dir = lambda: self.tmp.name

    def tearDown(self):
        paths.data_dir = self._orig
        self.tmp.cleanup()

    def test_remember_save_load_clear(self):
        s = sitebg.SiteBackgrounds()
        s.put("X.com", "#000000")
        s.put("example.org", "not a colour")           # ignored
        s.save()
        s2 = sitebg.SiteBackgrounds()
        self.assertEqual(s2.get("x.com"), "#000000")
        self.assertIsNone(s2.get("example.org"))
        s2.put("x.com", "")                            # a transparent page forgets the old colour
        self.assertIsNone(s2.get("x.com"))
        s2.put("a.com", "#101010")
        s2.clear()
        self.assertIsNone(sitebg.SiteBackgrounds().get("a.com"))

    def test_capped(self):
        s = sitebg.SiteBackgrounds()
        for i in range(sitebg.MAX + 50):
            s.put(f"h{i}.com", "#123456")
        self.assertLessEqual(len(s._map), sitebg.MAX)


if __name__ == "__main__":
    unittest.main()
