import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from null_browser.engine import google_compat as g  # noqa: E402

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"


class GoogleCompat(unittest.TestCase):
    def test_major_version(self):
        self.assertEqual(g.chrome_major(UA), "134")
        self.assertEqual(g.chrome_major(""), "130")

    def test_header_has_the_chrome_brand(self):
        h = g.client_hints(UA).decode()
        self.assertIn('"Google Chrome";v="134"', h)
        self.assertIn('"Chromium";v="134"', h)

    def test_only_google_hosts(self):
        for host in ("accounts.google.com", "google.com", "www.youtube.com", "fonts.gstatic.com"):
            self.assertTrue(g.is_google_host(host), host)
        for host in ("example.com", "notgoogle.com", "google.com.evil.example", "evilyoutube.com", ""):
            self.assertFalse(g.is_google_host(host), host)

    def test_script_is_scoped_and_filled_in(self):
        s = g.script_source("134")
        self.assertIn('"134"', s)
        self.assertNotIn("__MAJOR__", s)
        self.assertNotIn("__HOSTS__", s)
        self.assertIn("google", s)


if __name__ == "__main__":
    unittest.main()
