import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from null_browser.core import pwa  # noqa: E402

PAGE = "https://app.example.com/dashboard/index.html"
MAN = json.dumps({"name": "Example App", "short_name": "Ex", "start_url": "/dashboard/?src=pwa", "scope": "/dashboard/", "display": "standalone",
                  "theme_color": "#112233", "background_color": "#ffffff",
                  "icons": [{"src": "icons/48.png", "sizes": "48x48"}, {"src": "/i/192.png", "sizes": "192x192", "type": "image/png"},
                            {"src": "/i/512m.png", "sizes": "512x512", "purpose": "maskable"}, {"src": "javascript:alert(1)", "sizes": "99x99"}]})


class Manifest(unittest.TestCase):
    def test_parse(self):
        m = pwa.parse_manifest(MAN, "https://app.example.com/manifest.json", PAGE)
        self.assertEqual(m["name"], "Example App")
        self.assertEqual(m["start_url"], "https://app.example.com/dashboard/?src=pwa")
        self.assertEqual(m["scope"], "https://app.example.com/dashboard/")
        self.assertEqual(m["theme_color"], "#112233")
        self.assertEqual({i["src"] for i in m["icons"]}, {"https://app.example.com/icons/48.png", "https://app.example.com/i/192.png", "https://app.example.com/i/512m.png"})
        self.assertEqual(pwa.best_icon(m["icons"])["src"], "https://app.example.com/i/192.png")

    def test_cannot_move_to_another_site(self):
        evil = json.dumps({"name": "x", "start_url": "https://evil.example/", "scope": "https://evil.example/"})
        m = pwa.parse_manifest(evil, "https://app.example.com/m.json", PAGE)
        self.assertEqual(m["start_url"], PAGE)
        self.assertTrue(m["scope"].startswith("https://app.example.com/"))

    def test_missing_or_broken_manifest_uses_the_page(self):
        for text in ("", "not json", "[1]", "null"):
            m = pwa.parse_manifest(text, "", PAGE)
            self.assertEqual(m["start_url"], PAGE)
            self.assertEqual(m["display"], "standalone")
            self.assertEqual(m["icons"], [])

    def test_scope(self):
        sc = "https://app.example.com/dashboard/"
        self.assertTrue(pwa.in_scope("https://app.example.com/dashboard/a/b", sc))
        self.assertTrue(pwa.in_scope("https://app.example.com/dashboard", sc))
        self.assertFalse(pwa.in_scope("https://app.example.com/other", sc))
        self.assertFalse(pwa.in_scope("https://app.example.com.evil.net/dashboard/", sc))
        self.assertFalse(pwa.in_scope("http://app.example.com/dashboard/", sc))
        self.assertFalse(pwa.in_scope("javascript:alert(1)", sc))
        self.assertTrue(pwa.in_scope("https://app.example.com/anything", "https://app.example.com/"))

    def test_fingerprint_changes_when_the_site_updates_its_app(self):
        a = pwa.parse_manifest(MAN, "https://app.example.com/manifest.json", PAGE)
        b = pwa.parse_manifest(MAN.replace("Example App", "Example App 2"), "https://app.example.com/manifest.json", PAGE)
        c = pwa.parse_manifest(MAN, "https://app.example.com/manifest.json", PAGE)
        self.assertNotEqual(pwa.fingerprint(a), pwa.fingerprint(b))
        self.assertEqual(pwa.fingerprint(a), pwa.fingerprint(c))


class Store(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.store = pwa.PwaStore(self.dir)
        self.m = pwa.parse_manifest(MAN, "https://app.example.com/manifest.json", PAGE)

    def test_install_update_remove_persist(self):
        rec = self.store.add(self.m)
        again = pwa.PwaStore(self.dir)
        self.assertEqual(again.get(rec["id"])["name"], "Example App")
        self.assertEqual(self.store.add(self.m)["id"], rec["id"])                    # re-install = same app
        self.assertEqual(len(self.store.apps), 1)
        m2 = pwa.parse_manifest(MAN.replace("Example App", "Renamed"), "https://app.example.com/manifest.json", PAGE)
        self.store.apply_update(rec["id"], m2)
        self.assertEqual(pwa.PwaStore(self.dir).get(rec["id"])["name"], "Renamed")
        self.assertEqual(self.store.find_for_url("https://app.example.com/dashboard/x")["id"], rec["id"])
        self.assertIsNone(self.store.find_for_url("https://app.example.com/other"))
        self.store.remove(rec["id"])
        self.assertEqual(pwa.PwaStore(self.dir).apps, {})

    def test_app_data_is_outside_the_browser_profile_folder(self):
        aid = self.store.add(self.m)["id"]
        self.assertIn(os.path.join("data", aid), self.store.data_dir(aid))


if __name__ == "__main__":
    unittest.main()
